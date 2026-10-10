"""
HalalReady Backend — Messaging
Twilio WhatsApp primary, Telegram fallback after 2-hour limit.
CONTRACT.md §7: POST /tasks/{id}/send
"""

import os, asyncio, logging
from datetime import datetime, timedelta
from database import MYT

log = logging.getLogger("messaging")

# ── channel selection ───────────────────────────────────────────────

def get_channel() -> str:
    return os.getenv("MESSAGING_CHANNEL", "manual")


# ── Twilio WhatsApp ─────────────────────────────────────────────────

def send_whatsapp(to_phone: str, body: str) -> dict:
    """Send via Twilio WhatsApp.  Returns Twilio message SID."""
    from twilio.rest import Client
    client = Client(
        os.getenv("TWILIO_ACCOUNT_SID"),
        os.getenv("TWILIO_AUTH_TOKEN"),
    )
    msg = client.messages.create(
        from_=f'whatsapp:{os.getenv("TWILIO_WHATSAPP_FROM")}',
        to=f"whatsapp:{to_phone}",
        body=body,
    )
    log.info("WhatsApp sent: %s → %s", msg.sid, to_phone)
    return {"sid": msg.sid, "channel": "whatsapp", "status": "sent"}


# ── Telegram fallback ───────────────────────────────────────────────

async def send_telegram(body: str) -> dict:
    """Send to the owner's Telegram chat as a fallback."""
    import httpx
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_OWNER_CHAT_ID")
    if not token or not chat_id:
        return {"channel": "telegram", "status": "not_configured"}
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json={
            "chat_id": chat_id,
            "text": body,
            "parse_mode": "Markdown",
        })
    data = resp.json()
    log.info("Telegram sent: %s", data.get("ok"))
    return {"channel": "telegram", "status": "sent" if data.get("ok") else "error"}


# ── send with fallback logic ────────────────────────────────────────

async def send_message(to_phone: str | None, body: str, task_created_at: str | None = None) -> dict:
    """
    Proposal §6: Twilio WhatsApp primary; Telegram fallback after 2-hour limit.
    If the task was created >2 hours ago and WhatsApp hasn't been confirmed,
    fall back to Telegram.
    """
    channel = get_channel()

    if channel == "manual":
        log.info("Manual channel — message not sent automatically")
        return {"channel": "manual", "status": "manual"}

    # Check 2-hour fallback condition
    use_telegram_fallback = False
    if task_created_at and channel == "whatsapp":
        created = datetime.fromisoformat(task_created_at)
        if datetime.now(MYT) - created > timedelta(hours=2):
            use_telegram_fallback = True
            log.info("2-hour limit exceeded, falling back to Telegram")

    if channel == "whatsapp" and not use_telegram_fallback:
        if to_phone:
            try:
                return send_whatsapp(to_phone, body)
            except Exception as e:
                log.warning("WhatsApp failed (%s), falling back to Telegram", e)
                return await send_telegram(body)
        else:
            log.warning("No phone number, falling back to Telegram")
            return await send_telegram(body)

    # telegram channel or fallback
    return await send_telegram(body)
