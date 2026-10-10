"""
HalalReady backend: shared state and queries used by several routes.

- the live event hub behind the server-sent-events stream
- the "today" override for the demo date jump
- certificate, zone and readiness status for a business
- the Renewal Watch trigger (runs whenever the date changes)
"""

import asyncio
import json
import logging
from datetime import date
from pathlib import Path

from . import calculations as calc
from .database import (
    ROOT, ZONES, REQUIRED_DOCUMENTS, now_iso, fetch_all, fetch_one, insert,
)

log = logging.getLogger("state")


# ── live event hub ───────────────────────────────────────────────────

class EventHub:
    """Fan-out of new events to every open stream."""

    def __init__(self):
        self._queues: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        self._queues.discard(q)

    def publish(self, event: dict):
        for q in list(self._queues):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                log.warning("Dropping event for a slow stream subscriber")


hub = EventHub()


async def post_event(
    db, business_id: int, agent: str, label: str, status: str,
    handed_to: str | None = None, task_id: int | None = None,
    approval_id: int | None = None, run_id: int | None = None,
) -> dict:
    """Store an event, commit, and push it to the live stream."""
    if run_id is None:
        run = await active_run(db, business_id)
        run_id = run["id"] if run else None
    event = {
        "business_id": business_id, "run_id": run_id, "agent": agent,
        "label": label, "status": status, "handed_to": handed_to,
        "task_id": task_id, "approval_id": approval_id, "created_at": now_iso(),
    }
    event["id"] = await insert(db, "events", event)
    await db.commit()
    hub.publish(event)
    return event


# ── runs ─────────────────────────────────────────────────────────────

async def active_run(db, business_id: int) -> dict | None:
    return await fetch_one(
        db,
        "SELECT * FROM runs WHERE business_id = ? AND finished_at IS NULL ORDER BY id DESC LIMIT 1",
        (business_id,),
    )


# ── the "today" override ─────────────────────────────────────────────

async def get_today_override(db) -> str | None:
    row = await fetch_one(db, "SELECT value FROM settings WHERE key = 'today_override'")
    return row["value"] if row and row["value"] else None


async def get_today(db) -> date:
    return calc.effective_today(await get_today_override(db))


async def set_today_override(db, value: str | None):
    if value is not None:
        date.fromisoformat(value)  # validate
    await db.execute(
        "INSERT INTO settings (key, value) VALUES ('today_override', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (value,),
    )


# ── recognised certification bodies (rules/ is written by Person 3) ──

def issuer_recognised(issuer: str) -> bool | None:
    """
    Look the issuer up in rules/recognised_certifiers.json. Accepts either a
    list of names or a list of objects with name / short_name / aliases.
    Returns None when the list is not available, so nothing is guessed.
    """
    path = ROOT / "rules" / "recognised_certifiers.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("Could not read %s", path)
        return None
    if isinstance(data, dict):
        data = data.get("bodies") or data.get("certifiers") or []
    names: set[str] = set()
    for entry in data:
        if isinstance(entry, str):
            names.add(entry.strip().lower())
        elif isinstance(entry, dict):
            for key in ("name", "short_name", "abbreviation"):
                if entry.get(key):
                    names.add(str(entry[key]).strip().lower())
            for alias in entry.get("aliases", []) or []:
                names.add(str(alias).strip().lower())
    return issuer.strip().lower() in names


# ── statuses ─────────────────────────────────────────────────────────

async def ingredient_rows(db, business_id: int, today: date) -> list[dict]:
    """Every ingredient with its supplier, latest certificate and calculated status."""
    rows = await fetch_all(
        db,
        """SELECT i.*, s.name AS supplier_name,
                  c.id AS cert_id, c.issuer, c.cert_number, c.expiry_date,
                  c.issuer_recognised, c.file_id AS cert_file_id
           FROM ingredients i
           LEFT JOIN suppliers s ON s.id = i.supplier_id
           LEFT JOIN certificates c ON c.id = (
               SELECT MAX(id) FROM certificates WHERE ingredient_id = i.id)
           WHERE i.business_id = ?
           ORDER BY i.id""",
        (business_id,),
    )
    links = await fetch_all(
        db,
        """SELECT pi.ingredient_id, p.name FROM product_ingredients pi
           JOIN products p ON p.id = pi.product_id WHERE p.business_id = ?""",
        (business_id,),
    )
    products: dict[int, list[str]] = {}
    for link in links:
        products.setdefault(link["ingredient_id"], []).append(link["name"])

    for r in rows:
        cert = None
        if r["cert_id"] is not None:
            cert = {"issuer_recognised": r["issuer_recognised"], "expiry_date": r["expiry_date"]}
        r["status"] = calc.certificate_status(cert, today)
        r["days_to_expiry"] = calc.days_to_expiry(r["expiry_date"], today)
        r["issuer_recognised"] = None if r["issuer_recognised"] is None else bool(r["issuer_recognised"])
        r["products"] = products.get(r["id"], [])
    return rows


async def zone_rows(db, business_id: int) -> list[dict]:
    findings = await fetch_all(
        db,
        "SELECT * FROM site_findings WHERE business_id = ? ORDER BY id",
        (business_id,),
    )
    result = []
    for zone in ZONES:
        zf = [f for f in findings if f["zone"] == zone]
        result.append({"zone": zone, "status": calc.zone_status(zf), "findings": zf})
    return result


async def approved_doc_types(db, business_id: int) -> set[str]:
    rows = await fetch_all(
        db,
        "SELECT doc_type FROM documents WHERE business_id = ? AND status = 'approved'",
        (business_id,),
    )
    return {r["doc_type"] for r in rows}


async def readiness(db, business_id: int, today: date | None = None) -> dict:
    today = today or await get_today(db)
    ingredients = await ingredient_rows(db, business_id, today)
    zones = await zone_rows(db, business_id)
    return calc.readiness_score(
        [i["status"] for i in ingredients],
        {z["zone"]: z["status"] for z in zones},
        await approved_doc_types(db, business_id),
    )


# ── Renewal Watch trigger ────────────────────────────────────────────

async def upkeep_check(db, business_id: int) -> list[dict]:
    """
    Wake Renewal Watch for every certificate that is expiring or expired and
    has no renewal task yet. Called after a date change, and on demand.
    Returns the tasks created.
    """
    today = await get_today(db)
    created = []
    for ing in await ingredient_rows(db, business_id, today):
        if ing["status"] not in ("expiring", "expired") or ing["cert_id"] is None:
            continue
        ref = f"renewal:cert:{ing['cert_id']}"
        if await fetch_one(db, "SELECT id FROM tasks WHERE ref = ?", (ref,)):
            continue
        days = ing["days_to_expiry"]
        when = f"expires in {days} days" if days >= 0 else f"expired {-days} days ago"
        title = f"{ing['name']} certificate {when}"
        payload = {
            "ingredient_id": ing["id"], "certificate_id": ing["cert_id"],
            "supplier_id": ing["supplier_id"], "supplier_name": ing["supplier_name"],
            "expiry_date": ing["expiry_date"], "days_to_expiry": days,
        }
        task = {
            "business_id": business_id, "run_id": None, "from_agent": "system",
            "assignee": "renewal_watch", "title": title, "payload": json.dumps(payload),
            "ref": ref, "status": "open", "created_at": now_iso(),
        }
        task["id"] = await insert(db, "tasks", task)
        await post_event(
            db, business_id, "system", f"Date trigger: {ing['name']} certificate {'expiring' if days >= 0 else 'expired'}",
            "attention", handed_to="renewal_watch", task_id=task["id"],
        )
        created.append(task)

    # The business's own halal certificate
    biz = await fetch_one(db, "SELECT * FROM businesses WHERE id = ?", (business_id,))
    if biz and biz["halal_cert_expiry"]:
        days = calc.days_to_expiry(biz["halal_cert_expiry"], today)
        ref = f"renewal:business:{business_id}:{biz['halal_cert_expiry']}"
        if days is not None and days <= 180 and not await fetch_one(db, "SELECT id FROM tasks WHERE ref = ?", (ref,)):
            task = {
                "business_id": business_id, "run_id": None, "from_agent": "system",
                "assignee": "renewal_watch",
                "title": f"Own halal certificate expires in {days} days",
                "payload": json.dumps({"expiry_date": biz["halal_cert_expiry"], "days_to_expiry": days}),
                "ref": ref, "status": "open", "created_at": now_iso(),
            }
            task["id"] = await insert(db, "tasks", task)
            await post_event(db, business_id, "system", "Date trigger: own halal certificate renewal",
                             "attention", handed_to="renewal_watch", task_id=task["id"])
            created.append(task)
    return created


def safe_filename(name: str) -> str:
    """Strip any directory part and characters Windows can't store."""
    base = Path(name or "file").name
    cleaned = "".join(ch if ch.isalnum() or ch in "._- ()" else "_" for ch in base).strip()
    return cleaned or "file"


# ── task board ───────────────────────────────────────────────────────

async def create_task(
    db, business_id: int, from_agent: str, assignee: str, title: str,
    detail: str | None = None, payload: dict | None = None, ref: str | None = None,
    event_label: str | None = None, run_id: int | None = None,
) -> dict:
    """Put a task on the board and post the handoff event that draws the line on the graph."""
    if run_id is None:
        run = await active_run(db, business_id)
        run_id = run["id"] if run else None
    task = {
        "business_id": business_id, "run_id": run_id, "from_agent": from_agent,
        "assignee": assignee, "title": title, "detail": detail,
        "payload": json.dumps(payload) if payload is not None else None,
        "ref": ref, "status": "open", "created_at": now_iso(),
    }
    task["id"] = await insert(db, "tasks", task)
    event = await post_event(
        db, business_id, from_agent, event_label or title, "action",
        handed_to=assignee, task_id=task["id"], run_id=run_id,
    )
    task["payload"] = payload
    return {**task, "event_id": event["id"]}


def task_out(row: dict) -> dict:
    row = dict(row)
    if row.get("payload"):
        try:
            row["payload"] = json.loads(row["payload"])
        except ValueError:
            pass
    return row
