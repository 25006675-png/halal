"""
HalalReady backend: calculations.

Pure functions only (no database). Agents never calculate dates or scores;
they read the results of these through the connector.

"Today" is the demo override when one is set (see state.get_today), so the
demo can jump forward in time; otherwise the real date.
"""

from datetime import date

from .database import ZONES, REQUIRED_DOCUMENTS

EXPIRING_WITHIN_DAYS = 60

COVERED_STATUSES = ("valid", "expiring")


def effective_today(override: str | None) -> date:
    return date.fromisoformat(override) if override else date.today()


def days_to_expiry(expiry_date: str | None, today: date) -> int | None:
    """Days until expiry, negative once past. None when there is no date."""
    if not expiry_date:
        return None
    return (date.fromisoformat(expiry_date) - today).days


def certificate_status(cert: dict | None, today: date) -> str:
    """
    Status of an ingredient from its latest certificate:
      1. no certificate on file          -> missing
      2. the scan could not be read      -> unclear
      3. issuer known to be unrecognised -> unrecognised_issuer
      4. expiry before today             -> expired
      5. expiry within 60 days           -> expiring
      6. otherwise                       -> valid
    Source documents (natural ingredients) have no expiry and count as valid.
    """
    if cert is None:
        return "missing"
    if cert.get("legible") == 0:
        return "unclear"
    if cert.get("issuer_recognised") == 0:
        return "unrecognised_issuer"
    days = days_to_expiry(cert.get("expiry_date"), today)
    if days is None:
        return "valid"
    if days < 0:
        return "expired"
    if days <= EXPIRING_WITHIN_DAYS:
        return "expiring"
    return "valid"


def is_covered(status: str) -> bool:
    return status in COVERED_STATUSES


def zone_status(findings: list[dict]) -> str:
    """
    unchecked: the On-site Inspector has not recorded anything for the zone
    issue:     at least one open attention/problem finding
    clear:     checked, nothing open
    """
    if not findings:
        return "unchecked"
    for f in findings:
        if f["status"] == "open" and f["severity"] in ("attention", "problem"):
            return "issue"
    return "clear"


def readiness_score(
    ingredient_statuses: list[str],
    zone_statuses: dict[str, str],
    approved_doc_types: set[str],
) -> dict:
    """
    readiness = round(100 x (covered ingredients + clear zones + approved required documents)
                          / (all ingredients + 5 zones + 3 required documents))
    """
    covered = sum(1 for s in ingredient_statuses if is_covered(s))
    clear = sum(1 for z in ZONES if zone_statuses.get(z) == "clear")
    docs = sum(1 for d in REQUIRED_DOCUMENTS if d in approved_doc_types)
    total = len(ingredient_statuses) + len(ZONES) + len(REQUIRED_DOCUMENTS)
    done = covered + clear + docs
    return {
        "score": round(100 * done / total) if total else 0,
        "done": done,
        "total": total,
        "ingredients_covered": covered,
        "ingredients_total": len(ingredient_statuses),
        "zones_clear": clear,
        "zones_total": len(ZONES),
        "documents_approved": docs,
        "documents_total": len(REQUIRED_DOCUMENTS),
    }


def default_status_sentence(readiness: dict, problem_count: int, pending_approvals: int) -> str:
    """Fallback for the Today tab until the Coordinator writes its own sentence."""
    if readiness["ingredients_total"] == 0:
        return "Drop in your paperwork and site photos to get started."
    parts = [f"{readiness['score']}% ready."]
    if problem_count:
        parts.append(f"{problem_count} ingredient{'s' if problem_count != 1 else ''} still need a certificate.")
    if pending_approvals:
        parts.append(f"{pending_approvals} item{'s' if pending_approvals != 1 else ''} waiting for your approval.")
    if not problem_count and not pending_approvals:
        parts.append("Nothing needs you right now.")
    return " ".join(parts)
