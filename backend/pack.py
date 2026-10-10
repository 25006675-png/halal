"""
HalalReady backend: application pack.

The pack is built only from approved or verified items:
  - certificates whose status is valid or expiring
  - documents the owner approved
  - zones the On-site Inspector checked with nothing open
Anything else is listed on the cover sheet as missing, with the reason.

The app prepares the pack; the owner submits it to JAKIM herself.
Section order is provisional until it is matched to the MYeHALAL form.
"""

import csv
import html
import io
import zipfile
from datetime import datetime

from .database import UPLOAD_DIR, REQUIRED_DOCUMENTS, MYT, now_iso, fetch_all, fetch_one, insert
from .state import ingredient_rows, zone_rows, get_today

DISCLAIMER = (
    "Prepared with HalalReady from the owner's own records. This pack does not "
    "declare any product halal. Certification is decided by JAKIM; the owner "
    "submits the application through MYeHALAL herself."
)

STATUS_REASONS = {
    "missing": "no certificate on file",
    "expired": "certificate expired",
    "unrecognised_issuer": "issuer not on JAKIM's recognised list",
}


def file_path(row: dict):
    return UPLOAD_DIR / row["path"]


async def checklist(db, business_id: int) -> dict:
    today = await get_today(db)
    sections = []

    company_files = await fetch_all(
        db, "SELECT * FROM files WHERE business_id = ? AND category = 'company' ORDER BY id", (business_id,))
    items = [{"key": f"company:file:{f['id']}", "label": f["filename"], "status": "ready", "file_id": f["id"]}
             for f in company_files]
    if not items:
        items = [{"key": "company:registration", "label": "Company registration and profile",
                  "status": "missing", "reason": "nothing uploaded to the Company tray"}]
    sections.append({"section": "company", "title": "1. Company", "items": items})

    ingredients = await ingredient_rows(db, business_id, today)
    products = await fetch_all(db, "SELECT * FROM products WHERE business_id = ? ORDER BY id", (business_id,))
    sections.append({"section": "products", "title": "2. Products and ingredients", "items": [{
        "key": "products:matrix", "label": f"Ingredient matrix ({len(products)} products, {len(ingredients)} ingredients)",
        "status": "ready" if ingredients else "missing",
        "reason": None if ingredients else "no ingredients listed yet",
    }]})

    cert_items = []
    for ing in ingredients:
        label = ing["name"] + (f" ({ing['brand']})" if ing["brand"] else "")
        if ing["status"] in ("valid", "expiring"):
            note = f"expires {ing['expiry_date']}" if ing["expiry_date"] else "source document"
            if not ing["cert_file_id"]:
                note += "; on record, no scanned copy"
            cert_items.append({"key": f"cert:{ing['id']}", "label": label, "status": "ready",
                               "note": note, "file_id": ing["cert_file_id"]})
        else:
            cert_items.append({"key": f"cert:{ing['id']}", "label": label, "status": "missing",
                               "reason": STATUS_REASONS.get(ing["status"], ing["status"])})
    sections.append({"section": "certificates", "title": "3. Supplier certificates", "items": cert_items})

    docs = {d["doc_type"]: d for d in await fetch_all(
        db, "SELECT * FROM documents WHERE business_id = ?", (business_id,))}
    doc_items = []
    for doc_type, title in REQUIRED_DOCUMENTS.items():
        d = docs.get(doc_type)
        if d and d["status"] == "approved":
            doc_items.append({"key": f"doc:{doc_type}", "label": title, "status": "ready",
                              "document_id": d["id"], "note": f"version {d['version']}"})
        else:
            reason = "not written yet" if not d else {
                "draft": "draft, not yet sent for approval",
                "pending_approval": "waiting for your approval",
                "rejected": "you asked for changes",
            }[d["status"]]
            doc_items.append({"key": f"doc:{doc_type}", "label": title, "status": "missing",
                              "reason": reason, "document_id": d["id"] if d else None})
    sections.append({"section": "documents", "title": "4. Internal halal documents", "items": doc_items})

    zone_items = []
    for z in await zone_rows(db, business_id):
        label = f"Site self-check: {z['zone']}"
        if z["status"] == "clear":
            zone_items.append({"key": f"zone:{z['zone']}", "label": label, "status": "ready"})
        elif z["status"] == "issue":
            open_titles = [f["title"] for f in z["findings"]
                           if f["status"] == "open" and f["severity"] != "ok"]
            zone_items.append({"key": f"zone:{z['zone']}", "label": label, "status": "missing",
                               "reason": "open: " + "; ".join(open_titles)})
        else:
            zone_items.append({"key": f"zone:{z['zone']}", "label": label, "status": "missing",
                               "reason": "not checked yet"})
    sections.append({"section": "site", "title": "5. Premises self-check", "items": zone_items})

    all_items = [i for s in sections for i in s["items"]]
    ready = sum(1 for i in all_items if i["status"] == "ready")
    latest = await fetch_one(
        db, "SELECT id, created_at, items_ready, items_total FROM packs WHERE business_id = ? ORDER BY id DESC LIMIT 1",
        (business_id,))
    return {
        "today": today.isoformat(),
        "sections": sections,
        "items_total": len(all_items),
        "items_ready": ready,
        "complete": ready == len(all_items),
        "missing": [i for i in all_items if i["status"] == "missing"],
        "latest_pack": latest,
    }


def _cover_html(business: dict, check: dict) -> str:
    rows = []
    for s in check["sections"]:
        rows.append(f"<h2>{html.escape(s['title'])}</h2><table>")
        for i in s["items"]:
            mark = "&#10003;" if i["status"] == "ready" else "MISSING"
            cls = "ok" if i["status"] == "ready" else "miss"
            extra = i.get("note") or i.get("reason") or ""
            rows.append(f"<tr><td class='{cls}'>{mark}</td><td>{html.escape(i['label'])}</td>"
                        f"<td class='note'>{html.escape(extra)}</td></tr>")
        rows.append("</table>")
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Application pack: {html.escape(business['name'])}</title>
<style>
body{{font-family:Georgia,serif;max-width:780px;margin:40px auto;padding:0 16px;color:#2b2420;background:#fdfaf5}}
h1{{font-size:24px;margin-bottom:4px}} h2{{font-size:17px;margin-top:28px;border-bottom:1px solid #e3dccf;padding-bottom:4px}}
table{{width:100%;border-collapse:collapse}} td{{padding:5px 6px;vertical-align:top;border-bottom:1px solid #f0ebe1}}
td.ok{{color:#2f7d4f;width:80px;font-weight:bold}} td.miss{{color:#b3261e;width:80px;font-weight:bold}}
td.note{{color:#776b60;font-size:14px}} .meta{{color:#776b60}} .disc{{margin-top:32px;font-size:13px;color:#776b60}}
</style></head><body>
<h1>Halal application pack</h1>
<div class="meta">{html.escape(business['name'])} &middot; prepared {check['today']} &middot;
{check['items_ready']} of {check['items_total']} items ready</div>
{''.join(rows)}
<p class="disc">{html.escape(DISCLAIMER)}{' Sample case: all data is fictional.' if business.get('is_sample') else ''}</p>
</body></html>"""


async def assemble(db, business_id: int) -> dict:
    business = await fetch_one(db, "SELECT * FROM businesses WHERE id = ?", (business_id,))
    check = await checklist(db, business_id)
    today = await get_today(db)
    ingredients = await ingredient_rows(db, business_id, today)

    packs_dir = UPLOAD_DIR / "packs"
    packs_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(MYT).strftime("%Y%m%d-%H%M%S")
    rel_path = f"packs/HalalReady-pack-{business_id}-{stamp}.zip"

    files_by_id = {f["id"]: f for f in await fetch_all(
        db, "SELECT * FROM files WHERE business_id = ?", (business_id,))}

    def add_file(zf: zipfile.ZipFile, file_id: int | None, folder: str, prefix: str = ""):
        f = files_by_id.get(file_id) if file_id else None
        if f and file_path(f).exists():
            zf.write(file_path(f), f"{folder}/{prefix}{f['filename']}")

    with zipfile.ZipFile(UPLOAD_DIR / rel_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("00_cover_sheet.html", _cover_html(business, check))

        for item in check["sections"][0]["items"]:
            add_file(zf, item.get("file_id"), "1_company")

        matrix = io.StringIO()
        writer = csv.writer(matrix)
        writer.writerow(["Ingredient", "Brand", "Supplier", "Kind", "Proof", "Issuer",
                         "Certificate no.", "Expiry", "Status", "Used in"])
        for ing in ingredients:
            writer.writerow([ing["name"], ing["brand"] or "", ing["supplier_name"] or "", ing["kind"],
                             ing["proof_type"], ing["issuer"] or "", ing["cert_number"] or "",
                             ing["expiry_date"] or "", ing["status"], "; ".join(ing["products"])])
        zf.writestr("2_products/ingredient_matrix.csv", matrix.getvalue())

        for item in check["sections"][2]["items"]:
            if item["status"] == "ready":
                add_file(zf, item.get("file_id"), "3_certificates", f"{item['key'].split(':')[1]}_")

        docs = {d["id"]: d for d in await fetch_all(
            db, "SELECT * FROM documents WHERE business_id = ? AND status = 'approved'", (business_id,))}
        for item in check["sections"][3]["items"]:
            d = docs.get(item.get("document_id"))
            if item["status"] == "ready" and d:
                zf.writestr(f"4_documents/{d['doc_type']}.md", f"# {d['title']}\n\n{d['body'] or ''}\n")

        zones = await zone_rows(db, business_id)
        report = ["# Premises self-check", "",
                  "Pre-audit self-check from photos. It flags possible issues for the owner to check; "
                  "it is not an audit result.", ""]
        for z in zones:
            report.append(f"## {z['zone'].title()}: {z['status']}")
            for f in z["findings"]:
                state = "resolved" if f["status"] == "resolved" else f["severity"]
                report.append(f"- [{state}] {f['title']}" + (f": {f['detail']}" if f["detail"] else ""))
                add_file(zf, f["photo_file_id"], "5_site", f"{z['zone']}_")
            report.append("")
        zf.writestr("5_site/site_self_check.md", "\n".join(report))

    pack_id = await insert(db, "packs", {
        "business_id": business_id, "path": rel_path, "items_total": check["items_total"],
        "items_ready": check["items_ready"], "created_at": now_iso(),
    })
    return {"pack_id": pack_id, "path": rel_path, "items_total": check["items_total"],
            "items_ready": check["items_ready"], "complete": check["complete"],
            "missing": check["missing"], "download_url": f"/business/{business_id}/pack/download"}
