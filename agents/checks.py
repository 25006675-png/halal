"""
Work checks: before an agent may close a task, code checks the job was really
done. A missing step goes back to the same agent once, in the same session;
if it is still missing, the task closes with a "Needs attention" card for the
owner. Mistakes stop here instead of flowing into the next agent's work.

Each check reads the backend (the source of truth), never the agent's words.
"""

from . import tools, vision
from .tools import BUSINESS_ID, Ctx, norm


async def unmet(ctx: Ctx, task: dict) -> list[str]:
    """What is still missing for this task. Empty when the work is done (or the task has no check)."""
    title = norm(task["title"])
    check = None
    if ctx.agent == "coordinator":
        if task["from_agent"] == "owner":
            check = _coordinator_start
        elif title.startswith("update the owner"):
            check = _coordinator_wrap_up
    elif ctx.agent == "certificate_checker":
        if title.startswith("check every ingredient"):
            check = _checker_main
        elif title.startswith("undeclared brand on site"):
            check = _checker_undeclared
    elif ctx.agent == "onsite_inspector":
        if title.startswith("check the zone photos"):
            check = _inspector_zones
        elif title.startswith("declared brands"):
            check = _inspector_brands
    elif ctx.agent == "document_writer":
        if title.startswith("draft the halal policy"):
            check = _writer_policy
        elif title.startswith("confirmed ingredient"):
            check = _writer_procedures
    elif ctx.agent == "auditor" and title.startswith("review"):
        check = _auditor_review
    elif ctx.agent == "supplier_chaser" and title.startswith("ask"):
        check = _chaser_message
    return await check(ctx, task) if check else []


# ── helpers ──────────────────────────────────────────────────────────

async def _get(ctx: Ctx, path: str, **params):
    return await ctx.backend.call("GET", path, params=params or None)


async def _reading(ctx: Ctx, file_id: int) -> dict:
    data, ctype, meta = await ctx.backend.file(file_id)
    return await vision.read(data, ctype, meta["filename"])


def _mentions(text: str, name: str) -> bool:
    return bool(norm(name)) and norm(name) in norm(text)


# ── per task ─────────────────────────────────────────────────────────

async def _coordinator_start(ctx: Ctx, task: dict) -> list[str]:
    out = []
    files = await _get(ctx, "/agent/files", business_id=BUSINESS_ID)
    unsorted = [f["filename"] for f in files if not f["category"]]
    if unsorted:
        out.append("files not sorted: " + ", ".join(unsorted))
    approvals = await _get(ctx, f"/business/{BUSINESS_ID}/approvals")
    if not any(a["kind"] == "plan" for a in approvals):
        out.append("no plan proposed (call propose_plan)")
    return out


async def _coordinator_wrap_up(ctx: Ctx, task: dict) -> list[str]:
    overview = await _get(ctx, f"/business/{BUSINESS_ID}/overview")
    out = []
    if overview["status_by"] != "coordinator":
        out.append("no status sentence for Mak Teh (call set_status)")
    if not overview["latest_pack"]:
        out.append("the pack was not assembled (call assemble_pack)")
    return out


async def _checker_main(ctx: Ctx, task: dict) -> list[str]:
    out = []
    files = await _get(ctx, "/agent/files", business_id=BUSINESS_ID)
    ingredients = (await _get(ctx, "/agent/certificates", business_id=BUSINESS_ID))["ingredients"]
    declared = [i for i in ingredients if i["source"] == "declared"]
    brands = {norm(i["brand"]) for i in declared if i["brand"]}

    # every recipe line is a saved ingredient (matched on its brand)
    for f in files:
        if f["category"] == "products" and f["kind"] == "recipe":
            for line in (await _reading(ctx, f["id"])).get("recipe", {}).get("ingredients", []) or []:
                if line.get("brand") and norm(line["brand"]) not in brands:
                    out.append(f"recipe ingredient not saved: {line.get('name')} ({line['brand']})")
    # every certificate file has been recorded against an ingredient
    used = {i["cert_file_id"] for i in ingredients if i["cert_file_id"]}
    for f in files:
        if f["category"] == "suppliers" and f["kind"] == "certificate" and f["id"] not in used:
            out.append(f"certificate not recorded: {f['filename']} (call record_certificate)")
    # every open item has its next step: a supplier task, or a question for Mak Teh
    tasks = await _get(ctx, f"/business/{BUSINESS_ID}/tasks")
    approvals = await _get(ctx, f"/business/{BUSINESS_ID}/approvals")
    questions = {a["ingredient_id"] for a in approvals if a["kind"] == "question"}
    chased = [t for t in tasks if t["assignee"] == "supplier_chaser"]
    for i in declared:
        if i["status"] == "unclear" and i["id"] not in questions:
            out.append(f"{i['name']}: unreadable certificate but Mak Teh was not asked for a clearer copy")
        if i["status"] in ("missing", "expired", "unrecognised_issuer") and i["id"] not in questions and not any(
                _mentions(t["title"], i["name"]) or norm((t.get("payload") or {}).get("ingredient_name")) == norm(i["name"])
                for t in chased):
            out.append(f"{i['name']}: {i['status']} but no task for the Supplier Chaser")
    if not any(t["assignee"] == "onsite_inspector" and norm(t["title"]).startswith("declared brands") for t in tasks):
        out.append("the On-site Inspector did not get the declared brands")
    if not any(t["assignee"] == "document_writer" and norm(t["title"]).startswith("confirmed ingredient") for t in tasks):
        out.append("the Document Writer did not get the confirmed ingredient list")
    return out


async def _checker_undeclared(ctx: Ctx, task: dict) -> list[str]:
    brand = (task.get("payload") or {}).get("brand") or task["title"].split(":", 1)[-1]
    ingredients = (await _get(ctx, "/agent/certificates", business_id=BUSINESS_ID))["ingredients"]
    declared = any(i["source"] == "declared" and _mentions(i["brand"] or "", brand) for i in ingredients)
    if declared:
        return []
    out = []
    if not any(i["source"] == "found_on_site" and _mentions(i["brand"] or i["name"], brand) for i in ingredients):
        out.append(f"{brand} not recorded as found on site (save_ingredients with found_on_site=true)")
    approvals = await _get(ctx, f"/business/{BUSINESS_ID}/approvals")
    if not any(a["kind"] == "question" and _mentions(a["title"], brand) for a in approvals):
        out.append(f"Mak Teh was not asked about {brand} (ask_owner)")
    return out


async def _inspector_zones(ctx: Ctx, task: dict) -> list[str]:
    files = await _get(ctx, "/agent/files", business_id=BUSINESS_ID, category="site")
    site = await _get(ctx, f"/business/{BUSINESS_ID}/site")
    checked = {z["zone"] for z in site["zones"] if z["findings"]}
    return [f"{f['zone']} photo has no finding (save_site_finding)" for f in files
            if f["zone"] and f["zone"] not in checked]


async def _inspector_brands(ctx: Ctx, task: dict) -> list[str]:
    files = await _get(ctx, "/agent/files", business_id=BUSINESS_ID, category="site")
    store = next((f for f in files if f["zone"] == "store"), None)
    if not store:
        return []
    result = await tools.compare_store_brands(ctx, store["id"])
    if not result.get("ready"):
        return []
    site = await _get(ctx, f"/business/{BUSINESS_ID}/site")
    findings = next(z for z in site["zones"] if z["zone"] == "store")["findings"]
    tasks = await _get(ctx, f"/business/{BUSINESS_ID}/tasks", assignee="certificate_checker")
    out = []
    for b in result["undeclared"]:
        brand = b.get("brand", "")
        if not any(f["severity"] != "ok" and _mentions(f["title"] + " " + (f["detail"] or ""), brand) for f in findings):
            out.append(f"{brand} on the store shelf was not flagged (save_site_finding)")
        if not any(_mentions(t["title"], brand) for t in tasks):
            out.append(f"{brand} was not handed to the Certificate Checker")
    return out


async def _writer_policy(ctx: Ctx, task: dict) -> list[str]:
    return await _writer_docs(ctx, ["halal_policy"])


async def _writer_procedures(ctx: Ctx, task: dict) -> list[str]:
    return await _writer_docs(ctx, ["ingredient_control", "traceability"])


async def _writer_docs(ctx: Ctx, doc_types: list[str]) -> list[str]:
    docs = {d["doc_type"] for d in await _get(ctx, f"/business/{BUSINESS_ID}/documents")}
    tasks = await _get(ctx, f"/business/{BUSINESS_ID}/tasks", assignee="auditor")
    out = []
    for d in doc_types:
        if d not in docs:
            out.append(f"{d} not saved (save_document)")
        elif not any(d in norm(t["title"]).replace(" ", "_") for t in tasks):
            out.append(f"{d} not sent to the Auditor for review")
    return out


async def _auditor_review(ctx: Ctx, task: dict) -> list[str]:
    doc_type = next((d for d in ("halal_policy", "ingredient_control", "traceability")
                     if d in norm(task["title"]).replace(" ", "_")), None)
    if not doc_type:
        return []
    doc = next((d for d in await _get(ctx, f"/business/{BUSINESS_ID}/documents") if d["doc_type"] == doc_type), None)
    if doc and doc["status"] in ("pending_approval", "approved"):
        return []
    tasks = await _get(ctx, f"/business/{BUSINESS_ID}/tasks", assignee="document_writer")
    if any(norm(t["title"]).startswith("returned") and doc_type in norm(t["title"]).replace(" ", "_") for t in tasks):
        return []
    return [f"{doc_type} neither sent to Mak Teh for approval nor returned to the Writer"]


async def _chaser_message(ctx: Ctx, task: dict) -> list[str]:
    payload = task.get("payload") or {}
    supplier = payload.get("supplier_name") or ""
    approvals = await _get(ctx, f"/business/{BUSINESS_ID}/approvals")
    suppliers = {s["id"]: s["name"] for s in await _get(ctx, f"/business/{BUSINESS_ID}/suppliers")}
    if any(a["kind"] == "message" and (not supplier or _mentions(suppliers.get(a["supplier_id"], ""), supplier)
                                       or _mentions(task["title"], suppliers.get(a["supplier_id"], "")))
           for a in approvals):
        return []
    return ["no message drafted for Mak Teh to approve (request_supplier_message)"]

