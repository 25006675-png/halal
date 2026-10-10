"""
HalalReady backend: endpoints the MCP connector calls on behalf of agents.

Every route here sits under /agent and requires the X-Connector-Token header
when CONNECTOR_TOKEN is set. See CONTRACT.md §5 for the matching tools.
"""

import os
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from . import pack, state
from .database import (
    REQUIRED_DOCUMENTS, UPLOAD_DIR, connect, fetch_all, fetch_one, insert, now_iso, update,
)

Agent = Literal["coordinator", "certificate_checker", "supplier_chaser",
                "document_writer", "onsite_inspector", "renewal_watch"]
EventStatus = Literal["ok", "problem", "attention", "action", "info"]
Category = Literal["company", "products", "suppliers", "site"]
FileKind = Literal["invoice", "certificate", "recipe", "photo", "registration", "label", "other"]
Zone = Literal["store", "processing", "packing", "cleaning", "waste"]

DEFAULT_BUSINESS = int(os.getenv("BUSINESS_ID", "1"))


def require_connector(x_connector_token: str | None = Header(default=None)):
    expected = os.getenv("CONNECTOR_TOKEN")
    if expected and x_connector_token != expected:
        raise HTTPException(401, "Missing or wrong X-Connector-Token")


router = APIRouter(prefix="/agent", tags=["agent tools"], dependencies=[Depends(require_connector)])


async def _business(db, business_id: int) -> dict:
    biz = await fetch_one(db, "SELECT * FROM businesses WHERE id = ?", (business_id,))
    if not biz:
        raise HTTPException(404, f"Business {business_id} not found")
    return biz


async def _ingredient(db, business_id: int, ingredient_id: int | None, name: str | None) -> dict:
    if ingredient_id is not None:
        row = await fetch_one(db, "SELECT * FROM ingredients WHERE id = ? AND business_id = ?",
                              (ingredient_id, business_id))
    elif name:
        row = await fetch_one(db, "SELECT * FROM ingredients WHERE business_id = ? AND lower(name) = lower(?)",
                              (business_id, name.strip()))
    else:
        raise HTTPException(422, "Give ingredient_id or ingredient_name")
    if not row:
        raise HTTPException(404, f"Ingredient not found: {ingredient_id or name}")
    return row


async def _supplier(db, business_id: int, supplier_id: int | None, name: str | None) -> dict | None:
    if supplier_id is not None:
        row = await fetch_one(db, "SELECT * FROM suppliers WHERE id = ? AND business_id = ?",
                              (supplier_id, business_id))
    elif name:
        row = await fetch_one(db, "SELECT * FROM suppliers WHERE business_id = ? AND lower(name) = lower(?)",
                              (business_id, name.strip()))
    else:
        return None
    if not row:
        raise HTTPException(404, f"Supplier not found: {supplier_id or name}")
    return row


# ── events ───────────────────────────────────────────────────────────

class PostEvent(BaseModel):
    business_id: int = DEFAULT_BUSINESS
    agent: Agent
    label: str = Field(min_length=1, max_length=120)
    status: EventStatus
    handed_to: Optional[Agent] = None
    run_id: Optional[int] = None


@router.post("/events")
async def post_event(req: PostEvent):
    async with connect() as db:
        await _business(db, req.business_id)
        return await state.post_event(db, req.business_id, req.agent, req.label.strip(), req.status,
                                      handed_to=req.handed_to, run_id=req.run_id)


# ── task board ───────────────────────────────────────────────────────

class CreateTask(BaseModel):
    business_id: int = DEFAULT_BUSINESS
    from_agent: Agent
    assignee: Agent
    title: str = Field(min_length=1, max_length=200)
    detail: Optional[str] = None
    payload: Optional[dict[str, Any]] = None


@router.post("/tasks")
async def create_task(req: CreateTask):
    if req.from_agent == req.assignee:
        raise HTTPException(422, "A task must be handed to a different agent")
    async with connect() as db:
        await _business(db, req.business_id)
        return await state.create_task(db, req.business_id, req.from_agent, req.assignee,
                                       req.title, req.detail, req.payload)


@router.get("/tasks")
async def get_my_tasks(agent: Agent, business_id: int = DEFAULT_BUSINESS):
    """Open and in-progress tasks for this agent. Open ones are marked picked up."""
    async with connect() as db:
        rows = await fetch_all(
            db,
            """SELECT * FROM tasks WHERE business_id = ? AND assignee = ?
               AND status IN ('open', 'in_progress') ORDER BY id""",
            (business_id, agent),
        )
        now = now_iso()
        for r in rows:
            if r["status"] == "open":
                await update(db, "tasks", r["id"], {"status": "in_progress", "picked_up_at": now})
                r["status"], r["picked_up_at"] = "in_progress", now
        return [state.task_out(r) for r in rows]


class CompleteTask(BaseModel):
    agent: Agent
    result: Optional[str] = None


@router.post("/tasks/{task_id}/complete")
async def complete_task(task_id: int, req: CompleteTask):
    async with connect() as db:
        task = await fetch_one(db, "SELECT * FROM tasks WHERE id = ?", (task_id,))
        if not task:
            raise HTTPException(404, "Task not found")
        if task["assignee"] != req.agent:
            raise HTTPException(403, f"Task {task_id} belongs to {task['assignee']}, not {req.agent}")
        if task["status"] == "done":
            return state.task_out(task)
        values = {"status": "done", "result": req.result, "completed_at": now_iso()}
        await update(db, "tasks", task_id, values)
        await state.post_event(db, task["business_id"], req.agent, f"Done: {task['title']}"[:120], "ok",
                               task_id=task_id)
        return state.task_out({**task, **values})


# ── case and files ───────────────────────────────────────────────────

@router.get("/case")
async def get_case(business_id: int = DEFAULT_BUSINESS):
    """Everything an agent needs, with every date and status already calculated."""
    async with connect() as db:
        biz = await _business(db, business_id)
        today = await state.get_today(db)
        return {
            "business": biz,
            "today": today.isoformat(),
            "readiness": await state.readiness(db, business_id, today),
            "products": await fetch_all(db, "SELECT id, name FROM products WHERE business_id = ?", (business_id,)),
            "suppliers": await fetch_all(db, "SELECT * FROM suppliers WHERE business_id = ?", (business_id,)),
            "ingredients": await state.ingredient_rows(db, business_id, today),
            "documents": await fetch_all(
                db, "SELECT id, doc_type, title, version, status, updated_at FROM documents WHERE business_id = ?",
                (business_id,)),
            "zones": await state.zone_rows(db, business_id),
            "files": await fetch_all(
                db, "SELECT id, filename, category, kind, zone, supplier_id, source FROM files WHERE business_id = ?",
                (business_id,)),
            "required_documents": REQUIRED_DOCUMENTS,
        }


@router.get("/files")
async def get_files(business_id: int = DEFAULT_BUSINESS, category: Optional[Category] = None,
                    unsorted_only: bool = False):
    sql = "SELECT * FROM files WHERE business_id = ?"
    params: list = [business_id]
    if unsorted_only:
        sql += " AND category IS NULL"
    elif category:
        sql += " AND category = ?"
        params.append(category)
    async with connect() as db:
        rows = await fetch_all(db, sql + " ORDER BY id", params)
    for r in rows:
        r["content_url"] = f"/files/{r['id']}/content"
        r["local_path"] = str(UPLOAD_DIR / r["path"])
    return rows


class SortFile(BaseModel):
    category: Category
    kind: Optional[FileKind] = None
    zone: Optional[Zone] = None
    supplier_name: Optional[str] = None
    agent: Agent = "coordinator"


@router.post("/files/{file_id}/sort")
async def sort_file(file_id: int, req: SortFile):
    if req.zone and req.category != "site":
        raise HTTPException(422, "zone only applies to the site category")
    async with connect() as db:
        f = await fetch_one(db, "SELECT * FROM files WHERE id = ?", (file_id,))
        if not f:
            raise HTTPException(404, "File not found")
        supplier = await _supplier(db, f["business_id"], None, req.supplier_name) if req.supplier_name else None
        values = {"category": req.category, "kind": req.kind or f["kind"], "zone": req.zone,
                  "sorted_by": req.agent}
        if supplier:
            values["supplier_id"] = supplier["id"]
        await update(db, "files", file_id, values)
        return {**f, **values}


# ── ingredients and certificates ─────────────────────────────────────

class IngredientItem(BaseModel):
    name: str
    brand: Optional[str] = None
    kind: Literal["processed", "natural"]
    proof_type: Literal["halal_certificate", "source_document"]
    supplier_name: Optional[str] = None
    supplier_contact_name: Optional[str] = None
    supplier_phone: Optional[str] = None
    supplier_email: Optional[str] = None
    product_names: list[str] = []
    found_on_site: bool = False


class SaveIngredients(BaseModel):
    business_id: int = DEFAULT_BUSINESS
    ingredients: list[IngredientItem]


@router.post("/ingredients")
async def save_ingredients(req: SaveIngredients):
    """Insert or update by ingredient name, so repeated runs don't duplicate rows."""
    saved = []
    async with connect() as db:
        await _business(db, req.business_id)
        for item in req.ingredients:
            supplier_id = None
            if item.supplier_name:
                sup = await fetch_one(db, "SELECT * FROM suppliers WHERE business_id = ? AND lower(name) = lower(?)",
                                      (req.business_id, item.supplier_name.strip()))
                details = {k: v for k, v in {
                    "contact_name": item.supplier_contact_name, "phone": item.supplier_phone,
                    "email": item.supplier_email}.items() if v}
                if sup:
                    supplier_id = sup["id"]
                    # Don't overwrite a phone the owner set by hand for the demo.
                    if sup["phone"]:
                        details.pop("phone", None)
                    await update(db, "suppliers", supplier_id, details)
                else:
                    supplier_id = await insert(db, "suppliers", {
                        "business_id": req.business_id, "name": item.supplier_name.strip(), **details})

            existing = await fetch_one(db, "SELECT * FROM ingredients WHERE business_id = ? AND lower(name) = lower(?)",
                                       (req.business_id, item.name.strip()))
            values = {"brand": item.brand, "kind": item.kind, "proof_type": item.proof_type}
            if supplier_id:
                values["supplier_id"] = supplier_id
            if existing:
                ing_id = existing["id"]
                await update(db, "ingredients", ing_id, values)
            else:
                ing_id = await insert(db, "ingredients", {
                    "business_id": req.business_id, "name": item.name.strip(), **values,
                    "source": "found_on_site" if item.found_on_site else "declared", "created_at": now_iso()})

            for pname in item.product_names:
                prod = await fetch_one(db, "SELECT id FROM products WHERE business_id = ? AND lower(name) = lower(?)",
                                       (req.business_id, pname.strip()))
                pid = prod["id"] if prod else await insert(db, "products", {
                    "business_id": req.business_id, "name": pname.strip()})
                await db.execute("INSERT OR IGNORE INTO product_ingredients VALUES (?, ?)", (pid, ing_id))
            saved.append({"id": ing_id, "name": item.name, "created": existing is None,
                          "supplier_id": supplier_id})
    return {"saved": saved}


@router.get("/certificates")
async def get_certificates(business_id: int = DEFAULT_BUSINESS):
    """Every ingredient with certificate status and days to expiry."""
    async with connect() as db:
        today = await state.get_today(db)
        rows = await state.ingredient_rows(db, business_id, today)
    return {"today": today.isoformat(), "ingredients": rows}


class SaveCertificate(BaseModel):
    business_id: int = DEFAULT_BUSINESS
    ingredient_id: Optional[int] = None
    ingredient_name: Optional[str] = None
    issuer: str
    cert_number: Optional[str] = None
    expiry_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    issuer_recognised: Optional[bool] = None
    file_id: Optional[int] = None


@router.post("/certificates")
async def save_certificate(req: SaveCertificate):
    async with connect() as db:
        ing = await _ingredient(db, req.business_id, req.ingredient_id, req.ingredient_name)
        recognised = req.issuer_recognised
        if recognised is None:
            recognised = state.issuer_recognised(req.issuer)
        cert_id = await insert(db, "certificates", {
            "ingredient_id": ing["id"], "issuer": req.issuer, "cert_number": req.cert_number,
            "expiry_date": req.expiry_date,
            "issuer_recognised": None if recognised is None else int(recognised),
            "file_id": req.file_id, "created_at": now_iso()})
        today = await state.get_today(db)
        row = next(r for r in await state.ingredient_rows(db, req.business_id, today) if r["id"] == ing["id"])
    return {"certificate_id": cert_id, "ingredient_id": ing["id"], "ingredient": ing["name"],
            "status": row["status"], "days_to_expiry": row["days_to_expiry"],
            "issuer_recognised": row["issuer_recognised"], "today": today.isoformat()}


# ── documents ────────────────────────────────────────────────────────

class SaveDocument(BaseModel):
    business_id: int = DEFAULT_BUSINESS
    doc_type: str = Field(pattern=r"^[a-z_]+$")
    title: Optional[str] = None
    body: str
    agent: Agent = "document_writer"


@router.post("/documents")
async def save_document(req: SaveDocument):
    """Save a draft. Saving again over the same doc_type makes a new version."""
    title = req.title or REQUIRED_DOCUMENTS.get(req.doc_type) or req.doc_type.replace("_", " ").title()
    now = now_iso()
    async with connect() as db:
        await _business(db, req.business_id)
        existing = await fetch_one(db, "SELECT * FROM documents WHERE business_id = ? AND doc_type = ?",
                                   (req.business_id, req.doc_type))
        if existing:
            values = {"title": title, "body": req.body, "version": existing["version"] + 1,
                      "status": "draft", "written_by": req.agent, "updated_at": now}
            await update(db, "documents", existing["id"], values)
            # A new version replaces any approval request for the old one.
            await db.execute("UPDATE approvals SET status = 'rejected', comment = 'superseded by a new version' "
                             "WHERE document_id = ? AND status = 'pending'", (existing["id"],))
            return {**existing, **values}
        doc = {"business_id": req.business_id, "doc_type": req.doc_type, "title": title, "version": 1,
               "body": req.body, "status": "draft", "written_by": req.agent, "created_at": now, "updated_at": now}
        doc["id"] = await insert(db, "documents", doc)
        return doc


# ── site findings ────────────────────────────────────────────────────

class SaveSiteFinding(BaseModel):
    business_id: int = DEFAULT_BUSINESS
    zone: Zone
    severity: Literal["ok", "attention", "problem"]
    title: str
    detail: Optional[str] = None
    question: Optional[str] = None
    photo_file_id: Optional[int] = None


@router.post("/site-findings")
async def save_site_finding(req: SaveSiteFinding):
    """Use severity 'ok' to record a zone as checked with nothing found."""
    async with connect() as db:
        await _business(db, req.business_id)
        run = await state.active_run(db, req.business_id)
        row = {**req.model_dump(), "run_id": run["id"] if run else None,
               "status": "open", "created_at": now_iso()}
        row["id"] = await insert(db, "site_findings", row)
        zones = {z["zone"]: z["status"] for z in await state.zone_rows(db, req.business_id)}
    return {**row, "zone_status": zones[req.zone]}


# ── approvals ────────────────────────────────────────────────────────

class RequestApproval(BaseModel):
    business_id: int = DEFAULT_BUSINESS
    kind: Literal["message", "document"]
    agent: Agent
    title: Optional[str] = None
    supplier_id: Optional[int] = None
    supplier_name: Optional[str] = None
    ingredient_id: Optional[int] = None
    ingredient_name: Optional[str] = None
    document_id: Optional[int] = None
    doc_type: Optional[str] = None
    body_ms: Optional[str] = None
    body_en: Optional[str] = None


@router.post("/approvals")
async def request_approval(req: RequestApproval):
    """Put an approval card in the owner's 'Needs you' list. Nothing is sent before she approves."""
    async with connect() as db:
        await _business(db, req.business_id)
        values: dict = {"business_id": req.business_id, "kind": req.kind, "requested_by": req.agent}

        if req.kind == "document":
            if req.document_id is not None:
                doc = await fetch_one(db, "SELECT * FROM documents WHERE id = ?", (req.document_id,))
            elif req.doc_type:
                doc = await fetch_one(db, "SELECT * FROM documents WHERE business_id = ? AND doc_type = ?",
                                      (req.business_id, req.doc_type))
            else:
                raise HTTPException(422, "Give document_id or doc_type")
            if not doc:
                raise HTTPException(404, "Document not found; save it with save_document first")
            values.update(document_id=doc["id"], title=req.title or f"Review {doc['title']} (v{doc['version']})")
            await update(db, "documents", doc["id"], {"status": "pending_approval", "updated_at": now_iso()})
            dup_sql, dup_params = "document_id = ?", (doc["id"],)
        else:
            supplier = await _supplier(db, req.business_id, req.supplier_id, req.supplier_name)
            if not supplier:
                raise HTTPException(422, "A message needs supplier_id or supplier_name")
            if not (req.body_ms or req.body_en):
                raise HTTPException(422, "A message needs body_ms and/or body_en")
            ingredient = None
            if req.ingredient_id is not None or req.ingredient_name:
                ingredient = await _ingredient(db, req.business_id, req.ingredient_id, req.ingredient_name)
            values.update(supplier_id=supplier["id"], ingredient_id=ingredient["id"] if ingredient else None,
                          body_ms=req.body_ms, body_en=req.body_en,
                          title=req.title or f"Message to {supplier['name']}")
            dup_sql = "supplier_id = ? AND ifnull(ingredient_id, 0) = ?"
            dup_params = (supplier["id"], ingredient["id"] if ingredient else 0)

        existing = await fetch_one(
            db, f"SELECT * FROM approvals WHERE business_id = ? AND kind = ? AND status = 'pending' AND {dup_sql}",
            (req.business_id, req.kind, *dup_params))
        if existing:
            await update(db, "approvals", existing["id"], values)
            return {**existing, **values, "updated_existing": True}

        run = await state.active_run(db, req.business_id)
        values.update(run_id=run["id"] if run else None, status="pending", created_at=now_iso())
        values["id"] = await insert(db, "approvals", values)
        await db.commit()
        await state.post_event(db, req.business_id, req.agent, f"Needs your OK: {values['title']}"[:120],
                               "action", approval_id=values["id"])
        return values


# ── coordinator ──────────────────────────────────────────────────────

class SetStatus(BaseModel):
    business_id: int = DEFAULT_BUSINESS
    sentence: str = Field(min_length=1, max_length=300)


@router.post("/status")
async def set_status(req: SetStatus):
    """The Coordinator's one-sentence status for the owner's Today tab."""
    async with connect() as db:
        await _business(db, req.business_id)
        await update(db, "businesses", req.business_id,
                     {"status_sentence": req.sentence.strip(), "status_updated_at": now_iso()})
        score = await state.readiness(db, req.business_id)
    return {"sentence": req.sentence.strip(), "readiness": score}


@router.post("/pack")
async def assemble_pack(business_id: int = DEFAULT_BUSINESS):
    async with connect() as db:
        await _business(db, business_id)
        return await pack.assemble(db, business_id)
