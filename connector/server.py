"""
HalalReady MCP connector: one server, shared by all seven agents.

Every tool forwards to the backend (BACKEND_URL, default http://localhost:8000).
Agents never calculate dates or scores; those come back from the backend.

Run:
    python connector/server.py           # stdio (WorkBuddy starts it as a command)
    python connector/server.py --http    # streamable HTTP on http://127.0.0.1:8001/mcp
"""

import base64
import os
import sys
from pathlib import Path
from typing import Any, Literal, Optional

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP, Image
from mcp.server.fastmcp.exceptions import ToolError

import logging
logging.getLogger("httpx").setLevel(logging.WARNING)

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
TOKEN = os.getenv("CONNECTOR_TOKEN") or ""
BUSINESS_ID = int(os.getenv("BUSINESS_ID", "1"))

Agent = Literal["coordinator", "certificate_checker", "supplier_chaser",
                "document_writer", "onsite_inspector", "renewal_watch", "auditor"]
EventStatus = Literal["ok", "problem", "attention", "action", "info"]
Category = Literal["company", "products", "suppliers", "site"]
FileKind = Literal["invoice", "certificate", "recipe", "photo", "registration", "label", "other"]
Zone = Literal["store", "processing", "packing", "cleaning", "waste"]

INSTRUCTIONS = """HalalReady tools for a small Malaysian food factory preparing for halal certification.
Rules for every agent:
- Call post_event after every step, with a label of 8 words or fewer.
- Hand work to another agent with create_task; pick up your own work with get_my_tasks; close it with complete_task.
- Never send anything yourself. Supplier messages and documents go to the owner through request_approval.
- Never calculate dates, certificate status or the readiness score; read them from get_case or get_certificates.
- Never say anything is halal or not halal. Report what is documented and what is missing."""

mcp = FastMCP("halalready", instructions=INSTRUCTIONS, host="127.0.0.1",
              port=int(os.getenv("CONNECTOR_PORT", "8001")))


def _call(method: str, path: str, body: dict | None = None, params: dict | None = None) -> Any:
    headers = {"X-Connector-Token": TOKEN} if TOKEN else {}
    if body is not None:
        body = {k: v for k, v in body.items() if v is not None}
    if params is not None:
        params = {k: v for k, v in params.items() if v is not None}
    try:
        with httpx.Client(timeout=60) as client:
            resp = client.request(method, BACKEND_URL + path, json=body, params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise ToolError(f"Backend not reachable at {BACKEND_URL}: {exc}") from exc
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail")
        except ValueError:
            detail = resp.text
        raise ToolError(f"Backend refused ({resp.status_code}): {detail}")
    return resp.json()


# ── events and the task board ────────────────────────────────────────

@mcp.tool()
def post_event(agent: Agent, label: str, status: EventStatus, handed_to: Optional[Agent] = None) -> dict:
    """Post one step to the live dashboard. Call after every step. label: 8 words or fewer.
    status: ok (done, fine), problem (something wrong), attention (needs a look), action (working on it), info.
    Set handed_to when this step passes work to another agent."""
    return _call("POST", "/agent/events", {"business_id": BUSINESS_ID, "agent": agent, "label": label,
                                           "status": status, "handed_to": handed_to})


@mcp.tool()
def create_task(from_agent: Agent, assignee: Agent, title: str, detail: Optional[str] = None,
                payload: Optional[dict[str, Any]] = None) -> dict:
    """Hand work to another agent. Also posts the handoff event that draws the line on the dashboard.
    payload: structured data the other agent needs (ingredient ids, file ids, brand names...)."""
    return _call("POST", "/agent/tasks", {"business_id": BUSINESS_ID, "from_agent": from_agent,
                                          "assignee": assignee, "title": title, "detail": detail,
                                          "payload": payload})


@mcp.tool()
def get_my_tasks(agent: Agent) -> list[dict]:
    """Your open tasks, oldest first. Calling this marks them as picked up."""
    return _call("GET", "/agent/tasks", params={"agent": agent, "business_id": BUSINESS_ID})


@mcp.tool()
def complete_task(task_id: int, agent: Agent, result: Optional[str] = None) -> dict:
    """Close one of your tasks, with a one-line result."""
    return _call("POST", f"/agent/tasks/{task_id}/complete", {"agent": agent, "result": result})


# ── reading the case ─────────────────────────────────────────────────

@mcp.tool()
def get_case() -> dict:
    """The whole case: business, today's date, readiness score, products, suppliers, ingredients with
    calculated certificate status and days to expiry, documents, site zones and files."""
    return _call("GET", "/agent/case", params={"business_id": BUSINESS_ID})


@mcp.tool()
def get_files(category: Optional[Category] = None, unsorted_only: bool = False) -> list[dict]:
    """List uploaded files. unsorted_only=True gives the pile the Coordinator still has to sort."""
    return _call("GET", "/agent/files", params={"business_id": BUSINESS_ID, "category": category,
                                                "unsorted_only": unsorted_only})


@mcp.tool()
def read_file(file_id: int) -> Any:
    """Open an uploaded file. Images come back as images; text as text; other files as their local path."""
    headers = {"X-Connector-Token": TOKEN} if TOKEN else {}
    try:
        with httpx.Client(timeout=60) as client:
            resp = client.get(f"{BACKEND_URL}/files/{file_id}/content", headers=headers)
    except httpx.HTTPError as exc:
        raise ToolError(f"Backend not reachable: {exc}") from exc
    if resp.status_code >= 400:
        raise ToolError(f"File {file_id} not found")
    ctype = resp.headers.get("content-type", "").split(";")[0]
    if ctype.startswith("image/"):
        return Image(data=resp.content, format=ctype.split("/")[1])
    if ctype.startswith("text/") or ctype in ("application/json", "text/csv"):
        return resp.text
    files = _call("GET", "/agent/files", params={"business_id": BUSINESS_ID})
    match = next((f for f in files if f["id"] == file_id), None)
    return {"file_id": file_id, "content_type": ctype, "size_bytes": len(resp.content),
            "local_path": match["local_path"] if match else None,
            "note": "Not an image or text file. Open it from local_path.",
            "base64_head": base64.b64encode(resp.content[:64]).decode()}


@mcp.tool()
def sort_file(file_id: int, category: Category, kind: Optional[FileKind] = None, zone: Optional[Zone] = None,
              supplier_name: Optional[str] = None, agent: Agent = "coordinator") -> dict:
    """Coordinator: put a file in one of the four trays (company, products, suppliers, site).
    For site photos also give the zone (store, processing, packing, cleaning, waste)."""
    return _call("POST", f"/agent/files/{file_id}/sort", {"category": category, "kind": kind, "zone": zone,
                                                          "supplier_name": supplier_name, "agent": agent})


@mcp.tool()
def get_certificates() -> dict:
    """Every ingredient with certificate status (valid, expiring, expired, missing, unrecognised_issuer)
    and days to expiry, calculated by the backend for today's date."""
    return _call("GET", "/agent/certificates", params={"business_id": BUSINESS_ID})


# ── saving work ──────────────────────────────────────────────────────

@mcp.tool()
def save_ingredients(ingredients: list[dict[str, Any]]) -> dict:
    """Save ingredients (updates by name, so calling again is safe). Each item:
    {name, brand?, kind: processed|natural, proof_type: halal_certificate|source_document,
     supplier_name?, supplier_contact_name?, supplier_phone?, supplier_email?, product_names?: [..],
     found_on_site?: true for a brand the On-site Inspector found that was not declared}"""
    return _call("POST", "/agent/ingredients", {"business_id": BUSINESS_ID, "ingredients": ingredients})


@mcp.tool()
def save_certificate(issuer: Optional[str] = None, ingredient_id: Optional[int] = None,
                     ingredient_name: Optional[str] = None, cert_number: Optional[str] = None,
                     expiry_date: Optional[str] = None, issuer_recognised: Optional[bool] = None,
                     file_id: Optional[int] = None, legible: bool = True) -> dict:
    """Record a certificate (or source document) for an ingredient. expiry_date: YYYY-MM-DD.
    Leave issuer_recognised empty to have the backend check the recognised-bodies list.
    legible=False when the scan can't be read (status 'unclear'); never guess its details.
    Returns the calculated status."""
    return _call("POST", "/agent/certificates", {
        "business_id": BUSINESS_ID, "ingredient_id": ingredient_id, "ingredient_name": ingredient_name,
        "issuer": issuer, "cert_number": cert_number, "expiry_date": expiry_date,
        "issuer_recognised": issuer_recognised, "file_id": file_id, "legible": legible})


@mcp.tool()
def save_document(doc_type: str, body: str, title: Optional[str] = None,
                  agent: Agent = "document_writer") -> dict:
    """Save a draft document in Markdown. doc_type: halal_policy, ingredient_control or traceability
    (others allowed). Saving the same doc_type again creates a new version. Then call request_approval."""
    return _call("POST", "/agent/documents", {"business_id": BUSINESS_ID, "doc_type": doc_type,
                                              "title": title, "body": body, "agent": agent})


@mcp.tool()
def save_site_finding(zone: Zone, severity: Literal["ok", "attention", "problem"], title: str,
                      detail: Optional[str] = None, question: Optional[str] = None,
                      photo_file_id: Optional[int] = None) -> dict:
    """On-site Inspector: record what a zone photo shows. Use severity 'ok' when the zone looks fine,
    so it counts as checked. Use question for something only the owner can answer (pest control
    records, cleaning logs...). Flag possible issues; never conclude."""
    return _call("POST", "/agent/site-findings", {
        "business_id": BUSINESS_ID, "zone": zone, "severity": severity, "title": title,
        "detail": detail, "question": question, "photo_file_id": photo_file_id})


@mcp.tool()
def request_approval(kind: Literal["message", "document", "question"], agent: Agent, title: Optional[str] = None,
                     supplier_id: Optional[int] = None, supplier_name: Optional[str] = None,
                     ingredient_id: Optional[int] = None, ingredient_name: Optional[str] = None,
                     body_ms: Optional[str] = None, body_en: Optional[str] = None,
                     document_id: Optional[int] = None, doc_type: Optional[str] = None,
                     file_id: Optional[int] = None) -> dict:
    """Ask the owner to approve something. Nothing is sent until she does.
    kind=message: a supplier message; give the supplier, the ingredient it is about, and body_ms and/or body_en.
    kind=document: a saved document; give document_id or doc_type.
    kind=question: something only the owner can give; title + body_en, optional ingredient and file_id."""
    return _call("POST", "/agent/approvals", {
        "business_id": BUSINESS_ID, "kind": kind, "agent": agent, "title": title,
        "supplier_id": supplier_id, "supplier_name": supplier_name, "ingredient_id": ingredient_id,
        "ingredient_name": ingredient_name, "body_ms": body_ms, "body_en": body_en,
        "document_id": document_id, "doc_type": doc_type, "file_id": file_id})


@mcp.tool()
def set_status(sentence: str) -> dict:
    """Coordinator: the one-sentence status the owner sees first, e.g.
    '62% ready. Two suppliers still owe certificates; I've asked them both.' Use the score from get_case."""
    return _call("POST", "/agent/status", {"business_id": BUSINESS_ID, "sentence": sentence})


@mcp.tool()
def assemble_pack() -> dict:
    """Coordinator: build the application pack from approved items. Returns what is still missing."""
    return _call("POST", "/agent/pack", params={"business_id": BUSINESS_ID})


if __name__ == "__main__":
    mcp.run(transport="streamable-http" if "--http" in sys.argv else "stdio")
