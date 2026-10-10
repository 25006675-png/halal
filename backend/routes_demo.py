"""
HalalReady backend: one-click demo controls for the dashboard's Demo menu.

They use the fictional sample case in sample_case/ and the same code paths as
the real actions (upload, supplier reply, owner answer), so the stage flow and
its fallbacks behave like the real thing. Localhost only (see the tunnel guard).
"""

import io
import mimetypes
import shutil
import uuid

from fastapi import APIRouter, HTTPException, UploadFile
from starlette.datastructures import Headers

from . import state
from .database import ROOT, UPLOAD_DIR, connect, fetch_all, insert, now_iso, reset_db
from .routes_dashboard import answer_question, simulate_reply
from .seed import seed

router = APIRouter(prefix="/demo", tags=["demo"])

PILE = ROOT / "sample_case" / "pile"
KEPT = ROOT / "sample_case" / "kept_back"
DEMO_DAY = "2026-10-15"
BUSINESS_ID = 1


def _upload(path) -> UploadFile:
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return UploadFile(file=io.BytesIO(path.read_bytes()), filename=path.name,
                      headers=Headers({"content-type": ctype}))


@router.post("/reset")
async def demo_reset():
    """Empty everything, reseed, and set the demo date."""
    await reset_db()
    if UPLOAD_DIR.exists():
        shutil.rmtree(UPLOAD_DIR, ignore_errors=True)
    await seed()
    async with connect() as db:
        await state.set_today_override(db, DEMO_DAY)
    return {"reset": True, "today": DEMO_DAY}


@router.post("/load-sample")
async def load_sample():
    """Drop the sample pile, unsorted, as if the owner dragged it in."""
    files = sorted(p for p in PILE.glob("*") if p.is_file())
    if not files:
        raise HTTPException(404, "No sample files; run scripts/make_sample_case.py")
    (UPLOAD_DIR / "files").mkdir(parents=True, exist_ok=True)
    async with connect() as db:
        for f in files:
            rel = f"files/{uuid.uuid4().hex[:8]}_{f.name}"
            shutil.copyfile(f, UPLOAD_DIR / rel)
            await insert(db, "files", {
                "business_id": BUSINESS_ID, "filename": f.name, "path": rel,
                "content_type": mimetypes.guess_type(f.name)[0], "source": "upload", "uploaded_at": now_iso()})
        await db.commit()
        await state.post_event(db, BUSINESS_ID, "owner", f"Added {len(files)} files", "info", handed_to="coordinator")
    return {"files": len(files)}


async def _latest(kind: str, match) -> dict | None:
    async with connect() as db:
        rows = await fetch_all(db, """SELECT a.*, s.name AS supplier_name FROM approvals a
                                      LEFT JOIN suppliers s ON s.id = a.supplier_id
                                      WHERE a.business_id = ? AND a.kind = ? ORDER BY a.id DESC""",
                               (BUSINESS_ID, kind))
    return next((a for a in rows if match(a)), None)


@router.post("/supplier-reply")
async def supplier_reply():
    """Fallback for the live moment: Minyak Murni replies with the oil certificate."""
    a = await _latest("message", lambda a: a["status"] == "sent" and "murni" in (a["supplier_name"] or "").lower())
    if not a:
        raise HTTPException(409, "Approve and send the message to Minyak Murni first")
    return await simulate_reply(a["id"], "Salam Mak Teh, ini sijil halal minyak masak MURNI kami. Terima kasih.",
                                [_upload(KEPT / "reply_certificate_minyak_murni.png")])


@router.post("/owner-copy")
async def owner_copy():
    """The owner uploads the clearer ikan bilis certificate."""
    a = await _latest("question", lambda a: a["status"] == "pending" and "clearer" in a["title"].lower())
    if not a:
        raise HTTPException(409, "No 'clearer copy' question is waiting")
    return await answer_question(a["id"], "Here is a clearer copy.",
                                 [_upload(KEPT / "clear_copy_certificate_hasil_laut.png")])
