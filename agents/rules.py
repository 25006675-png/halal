"""
Deterministic rules the agents rely on. Pure functions, no model, no network,
so they behave the same every run and are covered by tests/test_rules.py.

- what a file really is (from its first bytes, not its name)
- which tray a file belongs in, from its structured reading
- whether text inside a file is trying to give instructions
- whether a flagged problem is backed by what the file reading shows
"""

import re
from pathlib import Path

# ── file type from content ───────────────────────────────────────────

MAGIC = [
    (b"\x89PNG\r\n\x1a\n", "image"), (b"\xff\xd8\xff", "image"), (b"GIF8", "image"),
    (b"%PDF", "pdf"), (b"PK\x03\x04", "office"),
]
EXT_KIND = {".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image", ".webp": "image",
            ".pdf": "pdf", ".xlsx": "office", ".xlsm": "office", ".docx": "office"}


def sniff(data: bytes) -> str:
    """'image', 'pdf', 'office' or 'unknown', from the file's first bytes."""
    head = data[:16]
    if head[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image"
    for magic, kind in MAGIC:
        if head.startswith(magic):
            return kind
    return "unknown"


def type_problem(data: bytes, filename: str) -> str | None:
    """A reason the file can't be trusted as what its name says, or None."""
    real = sniff(data)
    expected = EXT_KIND.get(Path(filename).suffix.lower())
    if real == "unknown":
        return "not an image, PDF, Excel or Word file"
    if expected and expected != real:
        return f"named like a {expected} file but it is a {real} file"
    return None


# ── trays, from the structured reading ───────────────────────────────

TRAY_OF = {
    "halal_certificate": ("suppliers", "certificate"), "invoice": ("suppliers", "invoice"),
    "supplier_list": ("suppliers", "other"), "recipe": ("products", "recipe"),
    "product_label": ("products", "label"), "company_registration": ("company", "registration"),
    "company_profile": ("company", "other"), "site_photo": ("site", "photo"),
}
ZONES = {"store", "processing", "packing", "cleaning", "waste"}


def tray_for(reading: dict, filename: str) -> dict | None:
    """{category, kind, zone?} for a file, or None when a person (or the Coordinator) must decide."""
    doc = reading.get("doc_type")
    if doc == "other" and not reading.get("legible") and re.search(r"cert|sijil", filename, re.I):
        return {"category": "suppliers", "kind": "certificate"}   # an unreadable certificate is still a certificate
    if doc not in TRAY_OF:
        return None
    category, kind = TRAY_OF[doc]
    out = {"category": category, "kind": kind}
    if category == "site":
        zone = (reading.get("site_photo") or {}).get("zone")
        if zone not in ZONES:
            return None
        out["zone"] = zone
    return out


# ── instructions hidden in a file ────────────────────────────────────

INJECTION = re.compile(
    r"ignore (all |the |any |your |previous |prior )*(rules|instructions|checks)"
    r"|disregard (all |the |your |previous )*(rules|instructions)"
    r"|(you are|act as) (an? |the )?(ai|assistant|agent|language model|chatbot)"
    r"|system prompt|developer message"
    r"|(approve|accept|pass|certify) (this|the) (case|application|file|document|certificate)"
    r"|mark (this|it|everything) as (valid|halal|approved|ok)", re.I)


def looks_like_instructions(*texts: str | None) -> bool:
    return any(t and INJECTION.search(t) for t in texts)


def reading_text(reading: dict) -> str:
    """Every string in a reading, joined, for the injection check."""
    out = []

    def walk(v):
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(reading)
    return " \n".join(out)


# ── evidence for a flagged problem ───────────────────────────────────

def words(text: str | None) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 3}


def flag_has_evidence(title: str, detail: str | None, reading: dict) -> bool:
    """A possible issue may be flagged only if the photo's reading shows it: a brand it names is on a label,
    or it shares at least two words with an issue the reading lists."""
    photo = reading.get("site_photo") or {}
    said = words(title) | words(detail)
    for b in photo.get("brands_visible") or []:
        brand = words(b.get("brand"))
        if brand and brand <= said:
            return True
    for issue in photo.get("possible_issues") or []:
        if len(words(issue) & said) >= 2:
            return True
    return False
