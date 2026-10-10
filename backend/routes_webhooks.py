"""
HalalReady backend: incoming supplier replies.

Twilio (WhatsApp) and Telegram call these through the public tunnel
(scripts/tunnel.py). A reply is matched to the supplier and to the last
message sent to them. Any attachment is filed in the Suppliers tray and
handed to the Certificate Checker as a task.
"""

import json
import logging
import mimetypes
import os
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from . import messaging, state
from .database import UPLOAD_DIR, connect, fetch_all, fetch_one, insert, now_iso, update

log = logging.getLogger("webhooks")
router = APIRouter(prefix="/webhooks", tags=["webhooks"])

DEFAULT_BUSINESS = int(os.getenv("BUSINESS_ID", "1"))


async def _latest_sent(db, where: str, params: tuple) -> dict | None:
    return await fetch_one(
        db, f"SELECT * FROM approvals WHERE kind = 'message' AND status IN ('sent', 'replied') AND {where} "
            "ORDER BY sent_at DESC, id DESC LIMIT 1", params)


async def record_reply(db, supplier: dict | None, approval: dict | None, text: str,
                       attachments: list[tuple[bytes, str, str | None]], via: str) -> dict:
    business_id = (supplier or approval or {}).get("business_id") or DEFAULT_BUSINESS
    who = supplier["name"] if supplier else "an unknown sender"

    file_ids = []
    target = UPLOAD_DIR / "files"
    target.mkdir(parents=True, exist_ok=True)
    for content, filename, content_type in attachments:
        name = state.safe_filename(filename)
        rel = f"files/{uuid.uuid4().hex[:8]}_{name}"
        (UPLOAD_DIR / rel).write_bytes(content)
        file_ids.append(await insert(db, "files", {
            "business_id": business_id, "category": "suppliers", "kind": "certificate",
            "supplier_id": supplier["id"] if supplier else None, "filename": name, "path": rel,
            "content_type": content_type, "source": "supplier_reply", "sorted_by": "system",
            "uploaded_at": now_iso()}))

    if approval:
        await update(db, "approvals", approval["id"], {
            "status": "replied", "reply_text": text or None,
            "reply_file_id": file_ids[0] if file_ids else None, "replied_at": now_iso()})
    await db.commit()

    approval_id = approval["id"] if approval else None
    await state.post_event(db, business_id, "supplier_chaser",
                           f"Reply from {who} via {via}" + (" with a file" if file_ids else ""),
                           "ok" if file_ids else "info", approval_id=approval_id)

    ingredient = None
    if approval and approval["ingredient_id"]:
        ingredient = await fetch_one(db, "SELECT id, name FROM ingredients WHERE id = ?", (approval["ingredient_id"],))
    payload = {
        "file_ids": file_ids, "approval_id": approval_id, "reply_text": text,
        "supplier_id": supplier["id"] if supplier else None, "supplier_name": supplier["name"] if supplier else None,
        "ingredient_id": ingredient["id"] if ingredient else None,
        "ingredient_name": ingredient["name"] if ingredient else None,
    }
    if file_ids:
        task = await state.create_task(
            db, business_id, "supplier_chaser", "certificate_checker",
            f"Check new certificate from {who}" + (f" for {ingredient['name']}" if ingredient else ""),
            detail=text or None, payload=payload,
            event_label=f"New certificate from {who}"[:120])
    else:
        task = await state.create_task(
            db, business_id, "system", "supplier_chaser", f"Read reply from {who}"[:200],
            detail=text or None, payload=payload, event_label=f"Reply from {who} to file"[:120])
    return {"task_id": task["id"], "file_ids": file_ids, "approval_id": approval_id}


# ── Twilio WhatsApp ──────────────────────────────────────────────────

async def public_url() -> str | None:
    """Set by scripts/tunnel.py at runtime; PUBLIC_WEBHOOK_URL in .env is the fallback."""
    async with connect() as db:
        row = await fetch_one(db, "SELECT value FROM settings WHERE key = 'public_webhook_url'")
    return (row and row["value"]) or os.getenv("PUBLIC_WEBHOOK_URL") or None


async def _check_twilio_signature(request: Request, params: dict):
    public_url_ = await public_url()
    token = os.getenv("TWILIO_AUTH_TOKEN")
    if not public_url_ or not token:
        log.warning("Twilio signature not checked: PUBLIC_WEBHOOK_URL or TWILIO_AUTH_TOKEN not set")
        return
    from twilio.request_validator import RequestValidator
    url = public_url_.rstrip("/") + "/webhooks/twilio"
    signature = request.headers.get("x-twilio-signature", "")
    if not RequestValidator(token).validate(url, params, signature):
        raise HTTPException(403, "Bad Twilio signature")


@router.post("/twilio")
async def twilio_webhook(request: Request):
    form = await request.form()
    params = {k: str(v) for k, v in form.items()}
    await _check_twilio_signature(request, params)

    sender = messaging.normalise_phone(params.get("From"))
    text = params.get("Body", "").strip()
    attachments = []
    for i in range(int(params.get("NumMedia", "0") or 0)):
        url = params.get(f"MediaUrl{i}")
        ctype = params.get(f"MediaContentType{i}") or "application/octet-stream"
        if not url:
            continue
        try:
            content = await messaging.download_twilio_media(url)
        except Exception as exc:
            log.warning("Could not download Twilio media %s: %s", url, exc)
            continue
        ext = mimetypes.guess_extension(ctype) or ""
        attachments.append((content, f"whatsapp_reply_{i + 1}{ext}", ctype))

    async with connect() as db:
        suppliers = await fetch_all(db, "SELECT * FROM suppliers WHERE phone IS NOT NULL")
        supplier = next((s for s in suppliers if messaging.normalise_phone(s["phone"]) == sender), None)
        approval = None
        if supplier:
            approval = await _latest_sent(db, "supplier_id = ?", (supplier["id"],))
        if not approval:
            sent = await fetch_all(db, "SELECT * FROM approvals WHERE kind = 'message' AND status IN ('sent', 'replied') "
                                       "AND recipient IS NOT NULL ORDER BY sent_at DESC")
            approval = next((a for a in sent if messaging.normalise_phone(a["recipient"]) == sender), None)
            if approval and not supplier:
                supplier = await fetch_one(db, "SELECT * FROM suppliers WHERE id = ?", (approval["supplier_id"],))
        await record_reply(db, supplier, approval, text, attachments, "WhatsApp")

    return Response("<?xml version='1.0' encoding='UTF-8'?><Response></Response>", media_type="application/xml")


# ── Telegram ─────────────────────────────────────────────────────────

@router.post("/telegram")
async def telegram_webhook(request: Request):
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET")
    if secret and request.headers.get("x-telegram-bot-api-secret-token") != secret:
        raise HTTPException(403, "Bad Telegram secret")

    update_ = await request.json()
    msg = update_.get("message") or update_.get("edited_message")
    if not msg:
        return {"ok": True}
    chat_id = str(msg["chat"]["id"])
    sender_name = " ".join(filter(None, [msg["chat"].get("first_name"), msg["chat"].get("last_name")])) \
        or msg["chat"].get("title") or ""
    text = (msg.get("text") or msg.get("caption") or "").strip()

    async with connect() as db:
        # Remember the last chat so the team can copy its id into .env or a supplier record.
        await db.execute(
            "INSERT INTO settings (key, value) VALUES ('telegram_last_chat', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (json.dumps({"chat_id": chat_id, "name": sender_name, "at": now_iso()}),))
        await db.commit()

        if text.startswith("/start"):
            try:
                await messaging.send_telegram(chat_id, f"Connected to HalalReady. Your chat id is {chat_id}.")
            except Exception as exc:
                log.warning("Could not answer /start: %s", exc)
            return {"ok": True}

        supplier = await fetch_one(db, "SELECT * FROM suppliers WHERE telegram_chat_id = ?", (chat_id,))
        approval = await _latest_sent(db, "recipient = ?", (chat_id,))
        if supplier and not approval:
            approval = await _latest_sent(db, "supplier_id = ?", (supplier["id"],))
        if approval and not supplier:
            supplier = await fetch_one(db, "SELECT * FROM suppliers WHERE id = ?", (approval["supplier_id"],))

        owner_chats = {os.getenv("TELEGRAM_OWNER_CHAT_ID")} | {
            b["owner_telegram_chat_id"] for b in await fetch_all(db, "SELECT owner_telegram_chat_id FROM businesses")}
        if not supplier and not approval and chat_id in owner_chats:
            return {"ok": True}  # the owner chatting with the bot is not a supplier reply

        attachments = []
        file_ref = None
        if msg.get("photo"):
            file_ref = (msg["photo"][-1]["file_id"], "telegram_photo.jpg", "image/jpeg")
        elif msg.get("document"):
            doc = msg["document"]
            file_ref = (doc["file_id"], doc.get("file_name") or "telegram_document",
                        doc.get("mime_type") or "application/octet-stream")
        if file_ref and messaging.telegram_configured():
            try:
                content, _ = await messaging.download_telegram_file(file_ref[0])
                attachments.append((content, file_ref[1], file_ref[2]))
            except Exception as exc:
                log.warning("Could not download Telegram file: %s", exc)

        await record_reply(db, supplier, approval, text, attachments, "Telegram")
    return {"ok": True}
