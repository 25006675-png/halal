"""
HalalReady backend: messaging.

Supplier messages go out only after the owner approves them.

- MESSAGING_CHANNEL=whatsapp: send through Twilio WhatsApp. If Twilio
  refuses the message, or no reply arrives within FALLBACK_AFTER_MINUTES
  (two hours by default), the same message is re-sent on Telegram.
- MESSAGING_CHANNEL=telegram: Telegram only.
- MESSAGING_CHANNEL=manual: nothing leaves the laptop; the dashboard shows
  the text for the owner to send herself. Safe default for development.

Replies come back through /webhooks/twilio and /webhooks/telegram, which
need the public tunnel URL (scripts/tunnel.py).
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta

import httpx

from .database import MYT

log = logging.getLogger("messaging")


def channel() -> str:
    value = os.getenv("MESSAGING_CHANNEL", "manual").strip().lower()
    return value if value in ("whatsapp", "telegram", "manual") else "manual"


def fallback_after() -> timedelta:
    return timedelta(minutes=float(os.getenv("FALLBACK_AFTER_MINUTES", "120")))


def twilio_configured() -> bool:
    return all(os.getenv(k) for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_WHATSAPP_FROM"))


def telegram_configured() -> bool:
    return bool(os.getenv("TELEGRAM_BOT_TOKEN"))


def status() -> dict:
    return {
        "channel": channel(),
        "twilio_configured": twilio_configured(),
        "telegram_configured": telegram_configured(),
        "fallback_after_minutes": fallback_after().total_seconds() / 60,
        "public_webhook_url": os.getenv("PUBLIC_WEBHOOK_URL") or None,
    }


def _wa(number: str) -> str:
    number = number.strip()
    return number if number.startswith("whatsapp:") else f"whatsapp:{number}"


def normalise_phone(value: str | None) -> str:
    """Digits only, so '+60 12-345 6789' and 'whatsapp:+60123456789' match."""
    return "".join(ch for ch in (value or "") if ch.isdigit())


def message_body(approval: dict, language: str) -> str:
    first, second = ("body_ms", "body_en") if language == "ms" else ("body_en", "body_ms")
    return approval.get(first) or approval.get(second) or approval["title"]


# ── raw senders ──────────────────────────────────────────────────────

async def send_whatsapp(to_phone: str, body: str) -> str:
    """Returns the Twilio message SID. Raises on failure."""
    if not twilio_configured():
        raise RuntimeError("Twilio is not configured")

    def _send():
        from twilio.rest import Client
        client = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])
        msg = client.messages.create(from_=_wa(os.environ["TWILIO_WHATSAPP_FROM"]), to=_wa(to_phone), body=body)
        return msg.sid

    sid = await asyncio.to_thread(_send)
    log.info("WhatsApp sent %s to %s", sid, to_phone)
    return sid


async def send_telegram(chat_id: str, body: str) -> str:
    """Returns the Telegram message id. Raises on failure."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Telegram is not configured")
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": body},
        )
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram error: {data.get('description')}")
    log.info("Telegram sent to chat %s", chat_id)
    return str(data["result"]["message_id"])


def supplier_telegram_chat(supplier: dict | None) -> str | None:
    """Supplier's own chat if known, else the demo fallback chat."""
    if supplier and supplier.get("telegram_chat_id"):
        return supplier["telegram_chat_id"]
    return os.getenv("TELEGRAM_FALLBACK_CHAT_ID") or None


# ── delivery with fallback ───────────────────────────────────────────

async def deliver(approval: dict, supplier: dict | None) -> dict:
    """
    Send an approved supplier message. Returns the fields to store on the
    approval: channel, recipient, external_id, send_error, status.
    """
    language = (supplier or {}).get("language") or "ms"
    body = message_body(approval, language)
    mode = channel()

    if mode == "manual":
        return {"channel": "manual", "recipient": (supplier or {}).get("phone"),
                "external_id": None, "send_error": None, "status": "sent"}

    errors = []
    if mode == "whatsapp":
        phone = (supplier or {}).get("phone")
        if phone:
            try:
                sid = await send_whatsapp(phone, body)
                return {"channel": "whatsapp", "recipient": phone, "external_id": sid,
                        "send_error": None, "status": "sent"}
            except Exception as exc:  # Twilio raises its own exception types
                log.warning("WhatsApp failed, trying Telegram: %s", exc)
                errors.append(f"whatsapp: {exc}")
        else:
            errors.append("whatsapp: supplier has no phone number")

    chat_id = supplier_telegram_chat(supplier)
    if chat_id:
        try:
            msg_id = await send_telegram(chat_id, body)
            return {"channel": "telegram", "recipient": chat_id, "external_id": msg_id,
                    "send_error": "; ".join(errors) or None, "status": "sent"}
        except Exception as exc:
            errors.append(f"telegram: {exc}")
    else:
        errors.append("telegram: no chat id for supplier and no TELEGRAM_FALLBACK_CHAT_ID")

    return {"channel": None, "recipient": None, "external_id": None,
            "send_error": "; ".join(errors), "status": "failed"}


def fallback_due(approval: dict, now: datetime | None = None) -> bool:
    """A WhatsApp message with no reply after the limit should go to Telegram."""
    if approval["status"] != "sent" or approval["channel"] != "whatsapp" or approval["fallback_at"]:
        return False
    sent_at = datetime.fromisoformat(approval["sent_at"])
    return (now or datetime.now(MYT)) - sent_at >= fallback_after()


async def notify_owner(business: dict, text: str) -> str | None:
    """Alert the owner on her own phone (no approval needed). Returns the channel used."""
    mode = channel()
    if mode == "manual":
        log.info("Owner alert (manual mode, not sent): %s", text)
        return None
    if mode == "whatsapp" and business.get("owner_phone") and twilio_configured():
        try:
            await send_whatsapp(business["owner_phone"], text)
            return "whatsapp"
        except Exception as exc:
            log.warning("Owner WhatsApp alert failed: %s", exc)
    chat_id = business.get("owner_telegram_chat_id") or os.getenv("TELEGRAM_OWNER_CHAT_ID")
    if chat_id and telegram_configured():
        try:
            await send_telegram(chat_id, text)
            return "telegram"
        except Exception as exc:
            log.warning("Owner Telegram alert failed: %s", exc)
    return None


# ── downloading reply attachments ────────────────────────────────────

async def download_twilio_media(url: str) -> bytes:
    auth = (os.getenv("TWILIO_ACCOUNT_SID", ""), os.getenv("TWILIO_AUTH_TOKEN", ""))
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url, auth=auth)
    resp.raise_for_status()
    return resp.content


async def download_telegram_file(file_id: str) -> tuple[bytes, str]:
    """Returns (content, file_path on Telegram's side)."""
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    async with httpx.AsyncClient(timeout=30) as client:
        meta = (await client.get(f"https://api.telegram.org/bot{token}/getFile",
                                 params={"file_id": file_id})).json()
        if not meta.get("ok"):
            raise RuntimeError(f"Telegram getFile failed: {meta.get('description')}")
        path = meta["result"]["file_path"]
        resp = await client.get(f"https://api.telegram.org/file/bot{token}/{path}")
    resp.raise_for_status()
    return resp.content, path
