"""Unit tests for the calculations and the messaging fallback. Run: python -m pytest tests"""

import asyncio
from datetime import date, datetime, timedelta

from backend import calculations as calc
from backend import messaging
from backend.database import MYT

TODAY = date(2026, 10, 10)


def cert(expiry=None, recognised=1):
    return {"expiry_date": expiry, "issuer_recognised": recognised}


def test_certificate_status_waterfall():
    assert calc.certificate_status(None, TODAY) == "missing"
    assert calc.certificate_status(cert("2030-01-01", 0), TODAY) == "unrecognised_issuer"
    assert calc.certificate_status(cert("2026-10-09"), TODAY) == "expired"
    assert calc.certificate_status(cert("2026-10-10"), TODAY) == "expiring"
    assert calc.certificate_status(cert("2026-12-09"), TODAY) == "expiring"   # 60 days
    assert calc.certificate_status(cert("2026-12-10"), TODAY) == "valid"      # 61 days
    assert calc.certificate_status(cert(None), TODAY) == "valid"              # source document
    assert calc.certificate_status(cert("2027-01-01", None), TODAY) == "valid"  # issuer not checked


def test_days_to_expiry_and_override():
    assert calc.days_to_expiry("2026-10-20", TODAY) == 10
    assert calc.days_to_expiry("2026-10-01", TODAY) == -9
    assert calc.days_to_expiry(None, TODAY) is None
    assert calc.effective_today("2027-02-10") == date(2027, 2, 10)


def test_zone_status():
    assert calc.zone_status([]) == "unchecked"
    assert calc.zone_status([{"status": "open", "severity": "ok"}]) == "clear"
    assert calc.zone_status([{"status": "open", "severity": "attention"}]) == "issue"
    assert calc.zone_status([{"status": "resolved", "severity": "problem"}]) == "clear"


def test_readiness_matches_demo_story():
    # 13 ingredients with 3 not covered, 3 of 5 zones clear, no documents approved -> 13/21 = 62%
    statuses = ["valid"] * 9 + ["expiring"] + ["expired", "missing", "missing"]
    zones = {"store": "issue", "packing": "issue", "processing": "clear", "cleaning": "clear", "waste": "clear"}
    r = calc.readiness_score(statuses, zones, set())
    assert (r["done"], r["total"], r["score"]) == (13, 21, 62)
    r = calc.readiness_score(["valid"], {z: "clear" for z in zones},
                             {"halal_policy", "ingredient_control", "traceability"})
    assert r["score"] == 100


def test_fallback_due_after_limit(monkeypatch):
    monkeypatch.setenv("FALLBACK_AFTER_MINUTES", "120")
    sent = datetime(2026, 10, 10, 9, 0, tzinfo=MYT)
    a = {"status": "sent", "channel": "whatsapp", "fallback_at": None, "sent_at": sent.isoformat()}
    assert not messaging.fallback_due(a, sent + timedelta(minutes=119))
    assert messaging.fallback_due(a, sent + timedelta(minutes=120))
    assert not messaging.fallback_due({**a, "status": "replied"}, sent + timedelta(hours=5))
    assert not messaging.fallback_due({**a, "channel": "telegram"}, sent + timedelta(hours=5))


def test_whatsapp_failure_falls_back_to_telegram(monkeypatch):
    monkeypatch.setenv("MESSAGING_CHANNEL", "whatsapp")
    monkeypatch.setenv("TELEGRAM_FALLBACK_CHAT_ID", "999")

    async def broken_whatsapp(phone, body):
        raise RuntimeError("63016 outside the allowed window")

    async def fake_telegram(chat_id, body):
        assert chat_id == "999" and body.startswith("Salam")
        return "42"

    monkeypatch.setattr(messaging, "send_whatsapp", broken_whatsapp)
    monkeypatch.setattr(messaging, "send_telegram", fake_telegram)
    approval = {"title": "t", "body_ms": "Salam", "body_en": "Hello"}
    result = asyncio.run(messaging.deliver(approval, {"phone": "+60120000000", "language": "ms"}))
    assert result["channel"] == "telegram" and result["status"] == "sent"
    assert "whatsapp" in result["send_error"]


def test_manual_mode_sends_nothing(monkeypatch):
    monkeypatch.setenv("MESSAGING_CHANNEL", "manual")
    result = asyncio.run(messaging.deliver({"title": "t", "body_en": "Hi"}, {"phone": "+601"}))
    assert result["channel"] == "manual" and result["external_id"] is None


def test_phone_normalisation():
    assert messaging.normalise_phone("whatsapp:+60 12-345 6789") == messaging.normalise_phone("+60123456789")
