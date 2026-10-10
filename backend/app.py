"""
HalalReady Backend — FastAPI application
CONTRACT.md §7: all dashboard endpoints
CONTRACT.md §5: connector-facing endpoints (post_event, etc.)
Proposal: documents, site_findings, approvals, pack assembly
"""

import os, json, asyncio, logging
from datetime import datetime, date
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from dotenv import load_dotenv

load_dotenv()

from database import get_db, init_db, MYT
from calculations import (
    effective_today, certificate_status, days_to_expiry,
    is_covered, readiness_score, SITE_AREAS,
)
from messaging import send_message

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("backend")

# ── SSE subscribers ─────────────────────────────────────────────────

# run_id → list[asyncio.Queue]
_subscribers: dict[int, list[asyncio.Queue]] = {}


def _publish_event(run_id: int, event_dict: dict):
    for q in _subscribers.get(run_id, []):
        q.put_nowait(event_dict)


# ── lifespan ────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await _seed_sample_data()
    yield


app = FastAPI(title="HalalReady Backend", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic models ────────────────────────────────────────────────

class PostEventReq(BaseModel):
    run_id: int
    agent: str
    label: str
    status: str
    finding_id: Optional[int] = None
    handed_to: Optional[str] = None

class SaveFindingReq(BaseModel):
    run_id: int
    agent: str
    category: str
    severity: str
    title: str
    detail: Optional[str] = None
    ingredient_id: Optional[int] = None
    area: Optional[str] = None

class CreateTaskReq(BaseModel):
    finding_id: Optional[int] = None
    type: str
    supplier_id: Optional[int] = None
    channel: str = "manual"
    body_ms: Optional[str] = None
    body_en: Optional[str] = None
    assignee: Optional[str] = None
    due_date: Optional[str] = None

class PatchTaskReq(BaseModel):
    body_ms: Optional[str] = None
    body_en: Optional[str] = None
    status: Optional[str] = None
    assignee: Optional[str] = None

class SaveIngredientItem(BaseModel):
    name: str
    brand: Optional[str] = None
    supplier_name: Optional[str] = None
    kind: str
    proof_type: str
    product_names: list[str] = []

class SaveIngredientsReq(BaseModel):
    business_id: int
    ingredients: list[SaveIngredientItem]

class SaveCertificateReq(BaseModel):
    ingredient_id: int
    issuer: str
    cert_number: str
    expiry_date: Optional[str] = None
    issuer_recognised: Optional[bool] = None
    file_id: Optional[int] = None

class SaveDocumentReq(BaseModel):
    business_id: int
    title: str
    body: Optional[str] = None

class SaveSiteFindingReq(BaseModel):
    business_id: int
    run_id: Optional[int] = None
    area: str
    severity: str
    title: str
    detail: Optional[str] = None
    photo_file_id: Optional[int] = None

class RequestApprovalReq(BaseModel):
    item_type: str     # 'task', 'document', 'message'
    item_id: int
    comment: Optional[str] = None

class ApprovalActionReq(BaseModel):
    action: str        # 'approve' or 'reject'
    comment: Optional[str] = None

class StartRunReq(BaseModel):
    sim_date: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════
# §5  CONNECTOR-FACING ENDPOINTS  (what agents call via the MCP connector)
# ═══════════════════════════════════════════════════════════════════

# ── post_event ──────────────────────────────────────────────────────

@app.post("/events")
async def post_event(req: PostEventReq):
    """CONTRACT.md §5 post_event — agents call after every step."""
    now = datetime.now(MYT).isoformat()
    db = await get_db()
    try:
        cur = await db.execute(
            """INSERT INTO events (run_id, agent, label, status, finding_id, handed_to, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (req.run_id, req.agent, req.label, req.status, req.finding_id, req.handed_to, now),
        )
        event_id = cur.lastrowid
        await db.commit()
        event = {
            "id": event_id, "run_id": req.run_id, "agent": req.agent,
            "label": req.label, "status": req.status,
            "finding_id": req.finding_id, "handed_to": req.handed_to,
            "created_at": now,
        }
        _publish_event(req.run_id, event)
        return event
    finally:
        await db.close()


# ── save_finding ────────────────────────────────────────────────────

@app.post("/findings")
async def save_finding(req: SaveFindingReq):
    """CONTRACT.md §5 save_finding"""
    now = datetime.now(MYT).isoformat()
    db = await get_db()
    try:
        cur = await db.execute(
            """INSERT INTO findings (run_id, agent, category, severity, title, detail,
                                     ingredient_id, area, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)""",
            (req.run_id, req.agent, req.category, req.severity, req.title,
             req.detail, req.ingredient_id, req.area, now),
        )
        finding_id = cur.lastrowid
        await db.commit()
        return {"id": finding_id, "status": "open"}
    finally:
        await db.close()


# ── create_task ─────────────────────────────────────────────────────

@app.post("/tasks")
async def create_task(req: CreateTaskReq):
    """CONTRACT.md §5 create_task — always created as 'draft'."""
    now = datetime.now(MYT).isoformat()
    db = await get_db()
    try:
        cur = await db.execute(
            """INSERT INTO tasks (finding_id, type, supplier_id, channel, body_ms, body_en,
                                  assignee, due_date, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?)""",
            (req.finding_id, req.type, req.supplier_id, req.channel,
             req.body_ms, req.body_en, req.assignee, req.due_date, now),
        )
        task_id = cur.lastrowid
        await db.commit()
        return {"id": task_id, "status": "draft"}
    finally:
        await db.close()


# ── get_my_tasks (proposal §6) ─────────────────────────────────────

@app.get("/tasks/agent/{agent}")
async def get_my_tasks(agent: str):
    """Proposal: agents pick up work handed to them."""
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT t.* FROM tasks t
               JOIN findings f ON t.finding_id = f.id
               WHERE t.status IN ('draft','approved') AND t.assignee = ?
               ORDER BY t.created_at""",
            (agent,),
        )
        return [dict(r) for r in rows]
    finally:
        await db.close()


# ── complete_task (proposal §6) ─────────────────────────────────────

@app.post("/tasks/{task_id}/complete")
async def complete_task(task_id: int):
    db = await get_db()
    try:
        await db.execute("UPDATE tasks SET status = 'done' WHERE id = ?", (task_id,))
        await db.commit()
        return {"id": task_id, "status": "done"}
    finally:
        await db.close()


# ── save_ingredients ────────────────────────────────────────────────

@app.post("/ingredients/batch")
async def save_ingredients(req: SaveIngredientsReq):
    """CONTRACT.md §5 save_ingredients"""
    db = await get_db()
    saved_ids = []
    try:
        for item in req.ingredients:
            # Find or create supplier
            supplier_id = None
            if item.supplier_name:
                row = await db.execute_fetchall(
                    "SELECT id FROM suppliers WHERE business_id = ? AND name = ?",
                    (req.business_id, item.supplier_name),
                )
                if row:
                    supplier_id = row[0]["id"]
                else:
                    cur = await db.execute(
                        "INSERT INTO suppliers (business_id, name) VALUES (?, ?)",
                        (req.business_id, item.supplier_name),
                    )
                    supplier_id = cur.lastrowid

            cur = await db.execute(
                """INSERT INTO ingredients (business_id, name, brand, supplier_id, kind, proof_type)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (req.business_id, item.name, item.brand, supplier_id, item.kind, item.proof_type),
            )
            ing_id = cur.lastrowid
            saved_ids.append(ing_id)

            # Link to products
            for pname in item.product_names:
                rows = await db.execute_fetchall(
                    "SELECT id FROM products WHERE business_id = ? AND name = ?",
                    (req.business_id, pname),
                )
                if rows:
                    await db.execute(
                        "INSERT OR IGNORE INTO product_ingredients VALUES (?, ?)",
                        (rows[0]["id"], ing_id),
                    )

        await db.commit()
        return {"saved_ids": saved_ids}
    finally:
        await db.close()


# ── save_certificate ────────────────────────────────────────────────

@app.post("/certificates")
async def save_certificate(req: SaveCertificateReq):
    """CONTRACT.md §5 save_certificate — returns id and calculated status."""
    db = await get_db()
    try:
        recognised = None if req.issuer_recognised is None else (1 if req.issuer_recognised else 0)
        cur = await db.execute(
            """INSERT INTO certificates (ingredient_id, issuer, cert_number, expiry_date,
                                         issuer_recognised, file_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (req.ingredient_id, req.issuer, req.cert_number, req.expiry_date,
             recognised, req.file_id),
        )
        cert_id = cur.lastrowid
        await db.commit()

        # Calculate status
        today = effective_today(None)  # Use real date for certificate saves
        status = certificate_status(
            has_cert=True,
            issuer_recognised=req.issuer_recognised,
            expiry_date=req.expiry_date,
            today=today,
        )
        return {"id": cert_id, "status": status}
    finally:
        await db.close()


# ── list_certificates ───────────────────────────────────────────────

@app.get("/business/{business_id}/certificates")
async def list_certificates(business_id: int, sim_date: Optional[str] = None):
    """CONTRACT.md §5 list_certificates — every ingredient with status + days."""
    today = effective_today(sim_date)
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT i.id as ingredient_id, i.name, i.brand, i.kind,
                      c.id as cert_id, c.issuer, c.cert_number, c.expiry_date,
                      c.issuer_recognised
               FROM ingredients i
               LEFT JOIN certificates c ON c.ingredient_id = i.id
               WHERE i.business_id = ?
               ORDER BY i.name""",
            (business_id,),
        )
        result = []
        for r in rows:
            has_cert = r["cert_id"] is not None
            recognised = None if r["issuer_recognised"] is None else bool(r["issuer_recognised"])
            status = certificate_status(has_cert, recognised, r["expiry_date"], today)
            dte = days_to_expiry(r["expiry_date"], today)
            result.append({
                "ingredient_id": r["ingredient_id"],
                "name": r["name"],
                "brand": r["brand"],
                "kind": r["kind"],
                "cert_id": r["cert_id"],
                "issuer": r["issuer"],
                "cert_number": r["cert_number"],
                "expiry_date": r["expiry_date"],
                "issuer_recognised": recognised,
                "status": status,
                "days_to_expiry": dte,
            })
        return result
    finally:
        await db.close()


# ── save_document (proposal) ───────────────────────────────────────

@app.post("/documents")
async def save_document(req: SaveDocumentReq):
    now = datetime.now(MYT).isoformat()
    db = await get_db()
    try:
        cur = await db.execute(
            """INSERT INTO documents (business_id, title, body, status, created_at, updated_at)
               VALUES (?, ?, ?, 'draft', ?, ?)""",
            (req.business_id, req.title, req.body, now, now),
        )
        doc_id = cur.lastrowid
        await db.commit()
        return {"id": doc_id, "status": "draft"}
    finally:
        await db.close()


# ── save_site_finding (proposal) ───────────────────────────────────

@app.post("/site-findings")
async def save_site_finding(req: SaveSiteFindingReq):
    now = datetime.now(MYT).isoformat()
    db = await get_db()
    try:
        cur = await db.execute(
            """INSERT INTO site_findings (business_id, run_id, area, severity, title,
                                          detail, photo_file_id, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)""",
            (req.business_id, req.run_id, req.area, req.severity, req.title,
             req.detail, req.photo_file_id, now),
        )
        sf_id = cur.lastrowid
        await db.commit()
        return {"id": sf_id, "status": "open"}
    finally:
        await db.close()


# ── request_approval (proposal) ────────────────────────────────────

@app.post("/approvals/request")
async def request_approval(req: RequestApprovalReq):
    """Mark an item as pending approval."""
    db = await get_db()
    try:
        if req.item_type == "task":
            await db.execute("UPDATE tasks SET status = 'draft' WHERE id = ?", (req.item_id,))
        elif req.item_type == "document":
            await db.execute(
                "UPDATE documents SET status = 'pending_approval' WHERE id = ?", (req.item_id,),
            )
        await db.commit()
        return {"item_type": req.item_type, "item_id": req.item_id, "pending": True}
    finally:
        await db.close()


# ═══════════════════════════════════════════════════════════════════
# §7  DASHBOARD-FACING ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

# ── GET /business/{id}/overview ─────────────────────────────────────

@app.get("/business/{business_id}/overview")
async def business_overview(business_id: int, sim_date: Optional[str] = None):
    today = effective_today(sim_date)
    db = await get_db()
    try:
        # Ingredient statuses
        rows = await db.execute_fetchall(
            """SELECT i.id, c.id as cert_id, c.expiry_date, c.issuer_recognised
               FROM ingredients i
               LEFT JOIN certificates c ON c.ingredient_id = i.id
               WHERE i.business_id = ?""",
            (business_id,),
        )
        statuses = []
        for r in rows:
            has_cert = r["cert_id"] is not None
            recognised = None if r["issuer_recognised"] is None else bool(r["issuer_recognised"])
            statuses.append(certificate_status(has_cert, recognised, r["expiry_date"], today))

        # Open site findings per area
        sf_rows = await db.execute_fetchall(
            "SELECT DISTINCT area FROM site_findings WHERE business_id = ? AND status = 'open'",
            (business_id,),
        )
        open_areas = {r["area"] for r in sf_rows}

        # Also check findings table for site findings
        f_rows = await db.execute_fetchall(
            """SELECT DISTINCT area FROM findings
               WHERE run_id IN (SELECT id FROM runs WHERE business_id = ?)
               AND category = 'site' AND status = 'open' AND area IS NOT NULL""",
            (business_id,),
        )
        open_areas.update(r["area"] for r in f_rows)

        score = readiness_score(statuses, open_areas)

        # Counters
        ing_count = len(statuses)
        cert_ok = sum(1 for s in statuses if is_covered(s))
        cert_problems = sum(1 for s in statuses if s in ("expired", "missing", "unrecognised_issuer"))

        task_rows = await db.execute_fetchall(
            """SELECT status, COUNT(*) as cnt FROM tasks
               WHERE finding_id IN (SELECT id FROM findings WHERE run_id IN
                   (SELECT id FROM runs WHERE business_id = ?))
               GROUP BY status""",
            (business_id,),
        )
        task_counts = {r["status"]: r["cnt"] for r in task_rows}

        # Next expiry
        next_exp = await db.execute_fetchall(
            """SELECT MIN(c.expiry_date) as next_expiry
               FROM certificates c
               JOIN ingredients i ON c.ingredient_id = i.id
               WHERE i.business_id = ? AND c.expiry_date >= ?""",
            (business_id, today.isoformat()),
        )
        next_expiry = next_exp[0]["next_expiry"] if next_exp else None

        # Business info
        biz = await db.execute_fetchall(
            "SELECT * FROM businesses WHERE id = ?", (business_id,),
        )
        if not biz:
            raise HTTPException(404, "Business not found")

        return {
            "business": dict(biz[0]),
            "readiness": score,
            "today": today.isoformat(),
            "ingredients_total": ing_count,
            "ingredients_covered": cert_ok,
            "ingredients_problems": cert_problems,
            "areas_clear": len(SITE_AREAS) - len(open_areas),
            "areas_total": len(SITE_AREAS),
            "tasks": task_counts,
            "next_expiry": next_expiry,
            "next_expiry_days": days_to_expiry(next_expiry, today) if next_expiry else None,
        }
    finally:
        await db.close()


# ── GET /business/{id}/ingredients ──────────────────────────────────

@app.get("/business/{business_id}/ingredients")
async def list_ingredients(business_id: int, sim_date: Optional[str] = None):
    today = effective_today(sim_date)
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT i.*, s.name as supplier_name,
                      c.id as cert_id, c.issuer, c.cert_number, c.expiry_date,
                      c.issuer_recognised
               FROM ingredients i
               LEFT JOIN suppliers s ON i.supplier_id = s.id
               LEFT JOIN certificates c ON c.ingredient_id = i.id
               WHERE i.business_id = ?
               ORDER BY i.name""",
            (business_id,),
        )
        result = []
        for r in rows:
            has_cert = r["cert_id"] is not None
            recognised = None if r["issuer_recognised"] is None else bool(r["issuer_recognised"])
            status = certificate_status(has_cert, recognised, r["expiry_date"], today)

            # Get linked products
            prods = await db.execute_fetchall(
                """SELECT p.name FROM products p
                   JOIN product_ingredients pi ON p.id = pi.product_id
                   WHERE pi.ingredient_id = ?""",
                (r["id"],),
            )

            result.append({
                **dict(r),
                "cert_status": status,
                "days_to_expiry": days_to_expiry(r["expiry_date"], today),
                "products": [p["name"] for p in prods],
            })
        return result
    finally:
        await db.close()


# ── GET /ingredients/{id} ──────────────────────────────────────────

@app.get("/ingredients/{ingredient_id}")
async def get_ingredient(ingredient_id: int, sim_date: Optional[str] = None):
    today = effective_today(sim_date)
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT i.*, s.name as supplier_name, s.phone, s.email,
                      c.id as cert_id, c.issuer, c.cert_number, c.expiry_date,
                      c.issuer_recognised, c.file_id
               FROM ingredients i
               LEFT JOIN suppliers s ON i.supplier_id = s.id
               LEFT JOIN certificates c ON c.ingredient_id = i.id
               WHERE i.id = ?""",
            (ingredient_id,),
        )
        if not rows:
            raise HTTPException(404, "Ingredient not found")
        r = rows[0]
        has_cert = r["cert_id"] is not None
        recognised = None if r["issuer_recognised"] is None else bool(r["issuer_recognised"])
        status = certificate_status(has_cert, recognised, r["expiry_date"], today)

        # Events mentioning this ingredient
        events = await db.execute_fetchall(
            """SELECT e.* FROM events e
               JOIN findings f ON e.finding_id = f.id
               WHERE f.ingredient_id = ?
               ORDER BY e.created_at DESC""",
            (ingredient_id,),
        )

        return {
            **dict(r),
            "cert_status": status,
            "days_to_expiry": days_to_expiry(r["expiry_date"], today),
            "history": [dict(ev) for ev in events],
        }
    finally:
        await db.close()


# ── POST /business/{id}/files ──────────────────────────────────────

@app.post("/business/{business_id}/files")
async def upload_file(
    business_id: int,
    kind: str = Form(...),
    file: UploadFile = File(...),
):
    upload_dir = os.getenv("UPLOAD_DIR", "./backend/uploads")
    os.makedirs(upload_dir, exist_ok=True)
    filepath = os.path.join(upload_dir, file.filename)
    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)

    now = datetime.now(MYT).isoformat()
    db = await get_db()
    try:
        cur = await db.execute(
            "INSERT INTO files (business_id, kind, filename, path, uploaded_at) VALUES (?,?,?,?,?)",
            (business_id, kind, file.filename, filepath, now),
        )
        file_id = cur.lastrowid
        await db.commit()
        return {"id": file_id, "filename": file.filename, "kind": kind}
    finally:
        await db.close()


# ── GET /business/{id}/files ───────────────────────────────────────

@app.get("/business/{business_id}/files")
async def get_files(business_id: int, kind: Optional[str] = None):
    db = await get_db()
    try:
        if kind:
            rows = await db.execute_fetchall(
                "SELECT * FROM files WHERE business_id = ? AND kind = ? ORDER BY uploaded_at DESC",
                (business_id, kind),
            )
        else:
            rows = await db.execute_fetchall(
                "SELECT * FROM files WHERE business_id = ? ORDER BY uploaded_at DESC",
                (business_id,),
            )
        return [dict(r) for r in rows]
    finally:
        await db.close()


# ── POST /business/{id}/runs ───────────────────────────────────────

@app.post("/business/{business_id}/runs")
async def start_run(business_id: int, req: StartRunReq = StartRunReq()):
    now = datetime.now(MYT).isoformat()
    db = await get_db()
    try:
        cur = await db.execute(
            "INSERT INTO runs (business_id, started_at, sim_date) VALUES (?, ?, ?)",
            (business_id, now, req.sim_date),
        )
        run_id = cur.lastrowid
        await db.commit()
        return {"id": run_id, "started_at": now, "sim_date": req.sim_date}
    finally:
        await db.close()


# ── GET /runs/{id} ──────────────────────────────────────────────────

@app.get("/runs/{run_id}")
async def get_run(run_id: int):
    db = await get_db()
    try:
        runs = await db.execute_fetchall("SELECT * FROM runs WHERE id = ?", (run_id,))
        if not runs:
            raise HTTPException(404, "Run not found")
        events = await db.execute_fetchall(
            "SELECT * FROM events WHERE run_id = ? ORDER BY created_at", (run_id,),
        )
        findings = await db.execute_fetchall(
            "SELECT * FROM findings WHERE run_id = ? ORDER BY created_at", (run_id,),
        )
        return {
            "run": dict(runs[0]),
            "events": [dict(e) for e in events],
            "findings": [dict(f) for f in findings],
        }
    finally:
        await db.close()


# ── GET /runs/{id}/stream — SSE live events ─────────────────────────

@app.get("/runs/{run_id}/stream")
async def stream_events(run_id: int, request: Request):
    """CONTRACT.md §6: Server-sent events, one JSON object per message."""
    queue: asyncio.Queue = asyncio.Queue()
    _subscribers.setdefault(run_id, []).append(queue)

    async def event_generator():
        try:
            # First send all existing events
            db = await get_db()
            try:
                rows = await db.execute_fetchall(
                    "SELECT * FROM events WHERE run_id = ? ORDER BY created_at",
                    (run_id,),
                )
                for r in rows:
                    yield {"data": json.dumps(dict(r))}
            finally:
                await db.close()

            # Then stream new events
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                    yield {"data": json.dumps(event)}
                except asyncio.TimeoutError:
                    yield {"comment": "keepalive"}
        finally:
            _subscribers.get(run_id, []).remove(queue)

    return EventSourceResponse(event_generator())


# ── GET /business/{id}/findings ─────────────────────────────────────

@app.get("/business/{business_id}/findings")
async def list_findings(business_id: int, status: Optional[str] = "open"):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT f.* FROM findings f
               JOIN runs r ON f.run_id = r.id
               WHERE r.business_id = ? AND (? IS NULL OR f.status = ?)
               ORDER BY f.created_at DESC""",
            (business_id, status, status),
        )
        return [dict(r) for r in rows]
    finally:
        await db.close()


# ── GET /business/{id}/tasks ───────────────────────────────────────

@app.get("/business/{business_id}/tasks")
async def list_tasks(business_id: int, status: Optional[str] = None):
    db = await get_db()
    try:
        if status:
            rows = await db.execute_fetchall(
                """SELECT t.* FROM tasks t
                   JOIN findings f ON t.finding_id = f.id
                   JOIN runs r ON f.run_id = r.id
                   WHERE r.business_id = ? AND t.status = ?
                   ORDER BY t.created_at DESC""",
                (business_id, status),
            )
        else:
            rows = await db.execute_fetchall(
                """SELECT t.* FROM tasks t
                   LEFT JOIN findings f ON t.finding_id = f.id
                   LEFT JOIN runs r ON f.run_id = r.id
                   WHERE r.business_id = ? OR t.finding_id IS NULL
                   ORDER BY t.created_at DESC""",
                (business_id,),
            )
        return [dict(r) for r in rows]
    finally:
        await db.close()


# ── PATCH /tasks/{id} ──────────────────────────────────────────────

@app.patch("/tasks/{task_id}")
async def patch_task(task_id: int, req: PatchTaskReq):
    db = await get_db()
    try:
        updates = []
        params = []
        if req.body_ms is not None:
            updates.append("body_ms = ?")
            params.append(req.body_ms)
        if req.body_en is not None:
            updates.append("body_en = ?")
            params.append(req.body_en)
        if req.status is not None:
            updates.append("status = ?")
            params.append(req.status)
        if req.assignee is not None:
            updates.append("assignee = ?")
            params.append(req.assignee)
        if not updates:
            raise HTTPException(400, "Nothing to update")
        params.append(task_id)
        await db.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?", params)
        await db.commit()

        # If approving, record it
        if req.status == "approved":
            now = datetime.now(MYT).isoformat()
            await db.execute(
                "INSERT INTO approvals (item_type, item_id, action, decided_by, decided_at) VALUES (?,?,?,?,?)",
                ("task", task_id, "approve", "owner", now),
            )
            await db.commit()

        rows = await db.execute_fetchall("SELECT * FROM tasks WHERE id = ?", (task_id,))
        return dict(rows[0]) if rows else {"id": task_id}
    finally:
        await db.close()


# ── POST /tasks/{id}/send ──────────────────────────────────────────

@app.post("/tasks/{task_id}/send")
async def send_task(task_id: int):
    """CONTRACT.md §7: send an approved message through the channel."""
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT t.*, s.phone, s.email FROM tasks t
               LEFT JOIN suppliers s ON t.supplier_id = s.id
               WHERE t.id = ?""",
            (task_id,),
        )
        if not rows:
            raise HTTPException(404, "Task not found")
        task = dict(rows[0])
        if task["status"] != "approved":
            raise HTTPException(400, "Task must be approved before sending")

        body = task["body_en"] or task["body_ms"] or ""
        result = await send_message(task.get("phone"), body, task["created_at"])

        await db.execute("UPDATE tasks SET status = 'sent' WHERE id = ?", (task_id,))
        await db.commit()
        return {"id": task_id, "status": "sent", "channel_result": result}
    finally:
        await db.close()


# ── GET /business/{id}/site-check ──────────────────────────────────

@app.get("/business/{business_id}/site-check")
async def site_check(business_id: int):
    db = await get_db()
    try:
        areas = {}
        for area in SITE_AREAS:
            findings = await db.execute_fetchall(
                """SELECT * FROM site_findings
                   WHERE business_id = ? AND area = ? AND status = 'open'
                   ORDER BY created_at DESC""",
                (business_id, area),
            )
            # Also pull from the general findings table
            gen_findings = await db.execute_fetchall(
                """SELECT * FROM findings
                   WHERE run_id IN (SELECT id FROM runs WHERE business_id = ?)
                   AND category = 'site' AND area = ? AND status = 'open'
                   ORDER BY created_at DESC""",
                (business_id, area),
            )
            all_findings = [dict(f) for f in findings] + [dict(f) for f in gen_findings]
            areas[area] = {
                "status": "problem" if all_findings else "clear",
                "findings": all_findings,
            }
        return areas
    finally:
        await db.close()


# ── GET /business/{id}/pack ────────────────────────────────────────

@app.get("/business/{business_id}/pack")
async def get_pack(business_id: int, sim_date: Optional[str] = None):
    """Pack checklist with item status.  Marks anything missing."""
    today = effective_today(sim_date)
    db = await get_db()
    try:
        # Required pack sections
        pack_sections = [
            {"section": "halal_policy", "title": "Halal Policy"},
            {"section": "ingredient_control", "title": "Ingredient Control Procedure"},
            {"section": "traceability", "title": "Traceability Procedure"},
            {"section": "ingredient_matrix", "title": "Ingredient Matrix"},
            {"section": "supplier_certificates", "title": "Supplier Certificates"},
            {"section": "site_report", "title": "Site Inspection Report"},
            {"section": "committee_letter", "title": "Halal Committee Appointment"},
            {"section": "process_flow", "title": "Process Flow Diagram"},
        ]

        # Check which documents exist and are approved
        docs = await db.execute_fetchall(
            "SELECT title, status FROM documents WHERE business_id = ?",
            (business_id,),
        )
        doc_titles = {d["title"].lower(): d["status"] for d in docs}

        # Check certificates coverage
        certs = await list_certificates(business_id, sim_date)
        all_covered = all(is_covered(c["status"]) for c in certs) if certs else False
        any_certs = len(certs) > 0

        # Check site findings
        sf = await db.execute_fetchall(
            "SELECT COUNT(*) as cnt FROM site_findings WHERE business_id = ? AND status = 'open'",
            (business_id,),
        )
        open_site = sf[0]["cnt"] if sf else 0

        result = []
        for sec in pack_sections:
            if sec["section"] == "supplier_certificates":
                status = "ready" if (any_certs and all_covered) else "missing"
            elif sec["section"] == "site_report":
                status = "ready" if open_site == 0 else "incomplete"
            elif sec["section"] == "ingredient_matrix":
                status = "ready" if any_certs else "missing"
            else:
                key = sec["title"].lower()
                if key in doc_titles:
                    status = "approved" if doc_titles[key] == "approved" else doc_titles[key]
                else:
                    status = "missing"
            result.append({**sec, "status": status})

        return {
            "sections": result,
            "complete": all(s["status"] in ("ready", "approved") for s in result),
            "readiness": readiness_score(
                [c["status"] for c in certs],
                {r["area"] for r in await db.execute_fetchall(
                    "SELECT DISTINCT area FROM site_findings WHERE business_id = ? AND status = 'open'",
                    (business_id,),
                )},
            ),
        }
    finally:
        await db.close()


# ── POST /webhooks/messaging ───────────────────────────────────────

@app.post("/webhooks/messaging")
async def incoming_webhook(request: Request):
    """Receive incoming supplier replies via Twilio/Telegram webhook."""
    body = await request.json()
    log.info("Incoming webhook: %s", json.dumps(body, indent=2))
    # Store the reply — in a real system we'd match it to a task
    return {"received": True}


# ── approval action endpoint ───────────────────────────────────────

@app.post("/approvals/{item_type}/{item_id}")
async def handle_approval(item_type: str, item_id: int, req: ApprovalActionReq):
    now = datetime.now(MYT).isoformat()
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO approvals (item_type, item_id, action, comment, decided_by, decided_at)
               VALUES (?, ?, ?, ?, 'owner', ?)""",
            (item_type, item_id, req.action, req.comment, now),
        )
        if item_type == "task":
            new_status = "approved" if req.action == "approve" else "draft"
            await db.execute("UPDATE tasks SET status = ? WHERE id = ?", (new_status, item_id))
        elif item_type == "document":
            new_status = "approved" if req.action == "approve" else "rejected"
            await db.execute(
                "UPDATE documents SET status = ?, updated_at = ? WHERE id = ?",
                (new_status, now, item_id),
            )
        await db.commit()
        return {"item_type": item_type, "item_id": item_id, "action": req.action}
    finally:
        await db.close()


# ── GET /business/{id}/documents ───────────────────────────────────

@app.get("/business/{business_id}/documents")
async def list_documents(business_id: int):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT * FROM documents WHERE business_id = ? ORDER BY updated_at DESC",
            (business_id,),
        )
        return [dict(r) for r in rows]
    finally:
        await db.close()


# ── get_case (connector tool) ──────────────────────────────────────

@app.get("/business/{business_id}/case")
async def get_case(business_id: int, sim_date: Optional[str] = None):
    """CONTRACT.md §5 get_case — full picture for agents."""
    today = effective_today(sim_date)
    db = await get_db()
    try:
        biz = await db.execute_fetchall("SELECT * FROM businesses WHERE id = ?", (business_id,))
        if not biz:
            raise HTTPException(404, "Business not found")
        products = await db.execute_fetchall(
            "SELECT * FROM products WHERE business_id = ?", (business_id,),
        )
        ingredients_raw = await db.execute_fetchall(
            """SELECT i.*, s.name as supplier_name,
                      c.id as cert_id, c.issuer, c.cert_number, c.expiry_date,
                      c.issuer_recognised
               FROM ingredients i
               LEFT JOIN suppliers s ON i.supplier_id = s.id
               LEFT JOIN certificates c ON c.ingredient_id = i.id
               WHERE i.business_id = ?""",
            (business_id,),
        )
        suppliers = await db.execute_fetchall(
            "SELECT * FROM suppliers WHERE business_id = ?", (business_id,),
        )
        files = await db.execute_fetchall(
            "SELECT * FROM files WHERE business_id = ?", (business_id,),
        )

        ingredients = []
        for r in ingredients_raw:
            has_cert = r["cert_id"] is not None
            recognised = None if r["issuer_recognised"] is None else bool(r["issuer_recognised"])
            status = certificate_status(has_cert, recognised, r["expiry_date"], today)
            ingredients.append({
                **dict(r),
                "cert_status": status,
                "days_to_expiry": days_to_expiry(r["expiry_date"], today),
            })

        return {
            "business": dict(biz[0]),
            "products": [dict(p) for p in products],
            "ingredients": ingredients,
            "suppliers": [dict(s) for s in suppliers],
            "files": [dict(f) for f in files],
        }
    finally:
        await db.close()


# ═══════════════════════════════════════════════════════════════════
# SAMPLE DATA SEED
# ═══════════════════════════════════════════════════════════════════

async def _seed_sample_data():
    """Seed the fictional Mak Teh sample case if no businesses exist."""
    db = await get_db()
    try:
        existing = await db.execute_fetchall("SELECT COUNT(*) as cnt FROM businesses")
        if existing[0]["cnt"] > 0:
            await db.close()
            return

        log.info("Seeding sample data for Mak Teh's Sambal Factory...")
        now = datetime.now(MYT).isoformat()

        # Business
        await db.execute(
            "INSERT INTO businesses (id, name) VALUES (1, ?)",
            ("Mak Teh's Sambal Dapur Sdn Bhd",),
        )

        # Products
        products = [
            (1, 1, "Sambal Tumis Mak Teh"),
            (2, 1, "Sambal Belacan Original"),
            (3, 1, "Sos Cili Mak Teh"),
        ]
        for p in products:
            await db.execute("INSERT INTO products (id, business_id, name) VALUES (?,?,?)", p)

        # Suppliers
        suppliers = [
            (1, 1, "KL Spice Trading Sdn Bhd", "Ahmad bin Ismail", "+60123456789", "ahmad@klspice.com.my"),
            (2, 1, "Seri Rempah Enterprise", "Fatimah binti Hassan", "+60198765432", "fatimah@serirempah.com"),
            (3, 1, "Global Oils (M) Bhd", "David Tan", "+60167891234", "david@globaloils.com.my"),
            (4, 1, "Belacan Melaka Asli", "Roslan bin Yusof", "+60134567890", "roslan@belacanmelaka.com"),
            (5, 1, "Kilang Gula Felda", None, "+60145678901", "orders@feldagula.com"),
        ]
        for s in suppliers:
            await db.execute(
                "INSERT INTO suppliers (id, business_id, name, contact_name, phone, email) VALUES (?,?,?,?,?,?)", s,
            )

        # Ingredients (12 per the sample case in CONTRACT.md)
        ingredients = [
            (1,  1, "Dried Chilli (Cili Kering)",     "Cap Naga",        1, "processed", "halal_certificate"),
            (2,  1, "Fresh Red Chilli",                None,              1, "natural",   "source_document"),
            (3,  1, "Shallots (Bawang Merah)",         None,              2, "natural",   "source_document"),
            (4,  1, "Garlic (Bawang Putih)",           None,              2, "natural",   "source_document"),
            (5,  1, "Belacan (Shrimp Paste)",          "Belacan Melaka",  4, "processed", "halal_certificate"),
            (6,  1, "Palm Cooking Oil",                "Saji",            3, "processed", "halal_certificate"),
            (7,  1, "Sugar (Gula Pasir)",              "Felda",           5, "processed", "halal_certificate"),
            (8,  1, "Salt (Garam)",                    "Cap Kapal",       2, "natural",   "source_document"),
            (9,  1, "Tamarind Paste (Asam Jawa)",      "Cap Limau",       2, "processed", "halal_certificate"),
            (10, 1, "Vinegar (Cuka)",                  "Heinz",           3, "processed", "halal_certificate"),
            (11, 1, "Modified Starch",                 "Ingredion",       3, "processed", "halal_certificate"),
            (12, 1, "Unknown Cooking Oil",             None,              None, "processed", "halal_certificate"),
        ]
        for ing in ingredients:
            await db.execute(
                "INSERT INTO ingredients (id, business_id, name, brand, supplier_id, kind, proof_type) VALUES (?,?,?,?,?,?,?)",
                ing,
            )

        # Product-ingredient links
        pi_links = [
            # Sambal Tumis uses: dried chilli, shallots, garlic, oil, sugar, salt, tamarind
            (1,1),(1,3),(1,4),(1,6),(1,7),(1,8),(1,9),
            # Sambal Belacan uses: fresh chilli, belacan, shallots, salt, sugar
            (2,2),(2,5),(2,3),(2,8),(2,7),
            # Sos Cili uses: dried chilli, vinegar, sugar, salt, starch, oil
            (3,1),(3,10),(3,7),(3,8),(3,11),(3,6),
        ]
        for pi in pi_links:
            await db.execute("INSERT INTO product_ingredients VALUES (?,?)", pi)

        # Certificates — some valid, some expired, some missing
        # Valid certs (9 covered per CONTRACT.md sample: 9/12 = 75% ingredients)
        certs = [
            (1, 1, "JAKIM",   "JAKIM/HC-2024/1234",  "2027-06-15", 1, None),    # Dried chilli – valid
            (2, 5, "JAKIM",   "JAKIM/HC-2024/5678",  "2026-08-10", 1, None),    # Belacan – EXPIRED
            (3, 6, "JAKIM",   "JAKIM/HC-2025/9012",  "2027-09-30", 1, None),    # Palm oil – valid
            (4, 7, "JAKIM",   "JAKIM/HC-2025/3456",  "2027-03-20", 1, None),    # Sugar – valid
            (5, 9, "MUI",     "MUI/2025/7890",        "2027-01-15", 1, None),    # Tamarind – valid
            (6, 10,"IFANCA",  "IFANCA-2025-1122",     "2027-05-01", 1, None),    # Vinegar – valid
            (7, 11,"JAKIM",   "JAKIM/HC-2025/3344",   "2027-08-22", 1, None),    # Starch – valid
        ]
        for c in certs:
            await db.execute(
                """INSERT INTO certificates (id, ingredient_id, issuer, cert_number,
                                             expiry_date, issuer_recognised, file_id)
                   VALUES (?,?,?,?,?,?,?)""", c,
            )
        # Source documents for natural ingredients (no expiry needed)
        source_docs = [
            (8,  2,  "Supplier",  "SD-FRC-001",   None, None, None),   # Fresh red chilli
            (9,  3,  "Supplier",  "SD-SHL-001",   None, None, None),   # Shallots
            (10, 4,  "Supplier",  "SD-GRL-001",   None, None, None),   # Garlic
            (11, 8,  "Supplier",  "SD-SLT-001",   None, None, None),   # Salt
        ]
        for sd in source_docs:
            await db.execute(
                """INSERT INTO certificates (id, ingredient_id, issuer, cert_number,
                                             expiry_date, issuer_recognised, file_id)
                   VALUES (?,?,?,?,?,?,?)""", sd,
            )
        # 9 ingredients covered (7 halal certs + 4 source docs - 2 problems)
        # ingredient 5 (belacan) is expired → not covered
        # ingredient 12 has NO cert → missing

        await db.commit()
        log.info("Sample data seeded: 1 business, 3 products, 12 ingredients, 5 suppliers, 7 certs")
    finally:
        await db.close()


# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
