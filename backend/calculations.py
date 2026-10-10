"""
HalalReady Backend — Calculations
CONTRACT.md §4: certificate status, readiness score, days-to-expiry.
All date logic uses the run's sim_date when set, else real date.
"""

from datetime import date, timedelta

SITE_AREAS = ["receiving", "dry_store", "production", "packing"]


def effective_today(sim_date: str | None) -> date:
    """Return the sim_date if provided, otherwise real today."""
    if sim_date:
        return date.fromisoformat(sim_date)
    return date.today()


def certificate_status(
    has_cert: bool,
    issuer_recognised: bool | None,
    expiry_date: str | None,
    today: date,
) -> str:
    """
    CONTRACT.md §4 — five-step waterfall:
      1. No certificate on file → missing
      2. issuer_recognised is false → unrecognised_issuer
      3. expiry_date before today → expired
      4. expiry_date within 60 days of today → expiring
      5. Otherwise → valid
    """
    if not has_cert:
        return "missing"
    if issuer_recognised is False:
        return "unrecognised_issuer"
    if expiry_date:
        exp = date.fromisoformat(expiry_date)
        if exp < today:
            return "expired"
        if (exp - today).days <= 60:
            return "expiring"
    return "valid"


def days_to_expiry(expiry_date: str | None, today: date) -> int | None:
    """Return days until expiry, negative if past.  None if no date."""
    if not expiry_date:
        return None
    return (date.fromisoformat(expiry_date) - today).days


def is_covered(status: str) -> bool:
    """An ingredient counts as covered when valid or expiring."""
    return status in ("valid", "expiring")


def readiness_score(
    ingredient_statuses: list[str],
    open_site_finding_areas: set[str],
) -> int:
    """
    CONTRACT.md §4:
    readiness = round(100 × (covered ingredients + clear areas)
                          / (all ingredients + 4 areas))
    """
    total_ingredients = len(ingredient_statuses)
    covered = sum(1 for s in ingredient_statuses if is_covered(s))
    clear_areas = sum(1 for a in SITE_AREAS if a not in open_site_finding_areas)
    denominator = total_ingredients + len(SITE_AREAS)
    if denominator == 0:
        return 0
    return round(100 * (covered + clear_areas) / denominator)
