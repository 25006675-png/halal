r"""
Smoke test for the safety structure, with no Gemini calls: it plays the agents
by calling their tools directly (file readings come from the cache), and checks
every guard does its job. Resets the demo case. The backend must be running.

    .venv\Scripts\python scripts/smoke_safety.py
"""

import asyncio
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from agents import tools  # noqa: E402

API = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
results = []


def expect(name, cond, info=""):
    results.append(bool(cond))
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"   [{info}]" if info and not cond else ""))


async def main():
    http = httpx.AsyncClient(base_url=API, timeout=60)
    assert (await http.get("/openapi.json")).json()["info"]["title"] == "HalalReady backend", "not our backend"
    await http.post("/demo/load-sample", params={"reset": "true"})
    await http.post("/business/1/runs", json={"mode": "prepare", "instruction": "Prepare the application."})
    b = tools.Backend()

    async def ctx_for(agent):
        tasks = (await http.get("/agent/tasks", params={"agent": agent, "business_id": 1})).json()
        return tools.Ctx(agent=agent, backend=b, task_ids=[t["id"] for t in tasks], tasks={t["id"]: t for t in tasks})

    call = tools.call

    print("Coordinator")
    c = await ctx_for("coordinator")
    tid = c.task_ids[0]
    r = await call(c, "complete_task", {"task_id": tid, "result": "done", "reply": "done"})
    expect("closing before doing the work is refused", "Not closed yet" in r.get("error", ""), r)
    r = (await call(c, "check_and_sort_pile", {}))["result"]
    expect("pile check sorts all 15 files by rule", r["sorted"] == 15 and not r["unplaced"], r)
    expect("pile check finds no problems in the sample case", not r["problems"], r["problems"])
    r = await call(c, "propose_plan", {"summary": "Sorted.", "steps": [{"assignee": "certificate_checker", "title": "x", "message": "Please check."}]})
    expect("plan proposed with the fixed step titles", "result" in r, r)
    r = await call(c, "complete_task", {"task_id": tid, "result": "planned", "reply": "Plan ready."})
    expect("closing after the work is accepted", r.get("result", {}).get("status") == "done", r)
    plan = next(a for a in (await http.get("/business/1/approvals")).json() if a["kind"] == "plan")
    await http.post(f"/approvals/{plan['id']}/approve", json={})

    print("Certificate Checker")
    k = await ctx_for("certificate_checker")
    tid = k.task_ids[0]
    files = {f["filename"]: f["id"] for f in (await http.get("/business/1/files")).json()}
    sup = lambda n, c, p: {"supplier_name": n, "supplier_contact_name": c, "supplier_phone": p}
    both = ["Sambal Tumis Mak Teh (250 g)", "Sambal Ikan Bilis Mak Teh (250 g)"]
    items = [
        {"name": "Dried chilli", "brand": "CILI MAJU", "kind": "natural", "product_names": both, **sup("Syarikat Cili Maju", "Encik Halim", "+60 11-0000 0101")},
        {"name": "Cooking oil", "brand": "MURNI", "kind": "processed", "product_names": both, **sup("Minyak Murni Sdn Bhd", "Puan Aishah", "+60 11-0000 0202")},
        {"name": "Shallot paste", "brand": "BAWANG SEGAR", "kind": "processed", "product_names": both, **sup("Bawang Segar Enterprise", "Encik Kumar", "+60 11-0000 0303")},
        {"name": "Garlic paste", "brand": "BAWANG SEGAR", "kind": "processed", "product_names": both, **sup("Bawang Segar Enterprise", "Encik Kumar", "+60 11-0000 0303")},
        {"name": "Sugar", "brand": "GULA MANIS", "kind": "processed", "product_names": both, **sup("Gula Manis Sdn Bhd", "Encik Lim", "+60 11-0000 0505")},
        {"name": "Ikan bilis", "brand": "HASIL LAUT", "kind": "natural", "product_names": both[1:], **sup("Hasil Laut Kuala", "Puan Zainab", "+60 11-0000 0404")},
    ]
    await call(k, "save_ingredients", {"ingredients": items})
    r = await call(k, "complete_task", {"task_id": tid, "result": "done", "reply": "done"})
    expect("half-done check is refused, with what is missing", "certificate not recorded" in r.get("error", ""), r)
    for fn, names in [("06_certificate_cili_maju.png", ["Dried chilli"]), ("07_certificate_bawang_segar.png", ["Shallot paste", "Garlic paste"]),
                      ("09_certificate_gula_manis.png", ["Sugar"]), ("08_certificate_hasil_laut.png", ["Ikan bilis"])]:
        r = (await call(k, "record_certificate", {"file_id": files[fn], "ingredient_names": names}))["result"]
    expect("unreadable scan recorded as unclear, nothing guessed", r["results"][0]["status"] == "unclear" and not r["results"][0]["expiry_date"], r)
    r = await call(k, "save_ingredients", {"ingredients": [{"name": "Cooking oil", "brand": "SURIAGOLD", "kind": "processed"}]})
    expect("a recorded brand can't be overwritten", "kept_existing" in r.get("result", {}), r)
    r = await call(k, "create_task", {"assignee": "supplier_chaser", "title": "Ask Hasil Laut Kuala for the Ikan bilis halal certificate",
                                      "message": "Please ask.", "payload": {"ingredient_name": "Ikan bilis"}})
    expect("an unclear item can't be sent to the Supplier Chaser", "waiting for Mak Teh" in r.get("error", ""), r)
    r = await call(k, "ask_owner", {"title": "Clearer copy needed: Ikan bilis certificate", "question": "Please upload a clearer copy.",
                                    "ingredient_name": "Ikan bilis", "file_id": files["08_certificate_hasil_laut.png"]})
    expect("clearer-copy question created", "result" in r, r)
    for args in [{"assignee": "supplier_chaser", "title": "Ask Minyak Murni Sdn Bhd for the Cooking oil halal certificate", "message": "No oil certificate on file.",
                  "payload": {"supplier_name": "Minyak Murni Sdn Bhd", "ingredient_name": "Cooking oil"}},
                 {"assignee": "onsite_inspector", "title": "Declared brands for the store check", "message": "Here are the brands.",
                  "payload": {"brands": ["CILI MAJU", "MURNI", "BAWANG SEGAR", "GULA MANIS", "HASIL LAUT"]}},
                 {"assignee": "document_writer", "title": "Confirmed ingredient and supplier list", "message": "Here is the list."}]:
        await call(k, "create_task", args)
    r = await call(k, "complete_task", {"task_id": tid, "result": "6 checked", "reply": "Done."})
    expect("complete check is accepted", r.get("result", {}).get("status") == "done", r)
    # The same job handed over, closed, and handed over again: the 4th time is refused.
    for n in range(4):
        r = await call(k, "create_task", {"assignee": "document_writer", "title": "Fix the supplier table" + (" again" if n else ""),
                                          "message": "Please fix it."})
        if "result" in r:
            w = await ctx_for("document_writer")
            for t in w.task_ids:
                if "supplier table" in w.tasks[t]["title"].lower():
                    await call(w, "complete_task", {"task_id": t, "result": "fixed", "reply": "Fixed."})
    expect("endless back-and-forth is stopped", "too many times" in r.get("error", ""), r)

    print("On-site Inspector")
    i = await ctx_for("onsite_inspector")
    store = files["11_photo_store.png"]
    r = await call(i, "save_site_finding", {"zone": "store", "severity": "problem", "title": "Rat droppings near the sacks", "photo_file_id": store})
    expect("a flag the photo doesn't show is rejected", "does not show" in r.get("error", ""), r)
    r = await call(i, "save_site_finding", {"zone": "store", "severity": "problem", "title": "Undeclared brand: CAP MERPATI HIJAU Minyak Masak", "photo_file_id": store})
    expect("a flag the photo shows is accepted", "result" in r, r)
    r = (await call(i, "compare_store_brands", {"file_id": store}))["result"]
    expect("brand comparison finds only Cap Merpati Hijau", [u["brand"] for u in r["undeclared"]] == ["CAP MERPATI HIJAU"], r["undeclared"])
    # A question about an undeclared item, with the store photo attached, must not mark it "unclear".
    await call(k, "save_ingredients", {"ingredients": [{"name": "Minyak Masak (CAP MERPATI HIJAU, found on site)",
                                                        "brand": "CAP MERPATI HIJAU", "kind": "processed", "found_on_site": True}]})
    await call(k, "ask_owner", {"title": "Undeclared item in store: CAP MERPATI HIJAU", "question": "Is it used?",
                                "ingredient_name": "Minyak Masak (CAP MERPATI HIJAU, found on site)", "file_id": store})
    await call(k, "ask_owner", {"title": "Undeclared item in store: CAP MERPATI HIJAU (no file)", "question": "Is it used?",
                                "ingredient_name": "Minyak Masak (CAP MERPATI HIJAU, found on site)"})
    ing = next(x for x in (await http.get("/business/1/ingredients")).json() if x["source"] == "found_on_site")
    expect("a photo attached to a question doesn't make an item 'unclear'", ing["status"] == "missing", ing["status"])

    print("Files")
    f = (await http.get("/business/1/files")).json()[0]
    expect("every file has a fingerprint", all(x.get("sha256") for x in (await http.get("/business/1/files")).json()))
    path = ROOT / "backend" / "uploads" / f["path"]
    original = path.read_bytes()
    path.write_bytes(original + b"tampered")
    r = await http.get(f"/files/{f['id']}/content")
    path.write_bytes(original)
    expect("a file changed after upload is refused", r.status_code == 409, r.status_code)

    await http.post("/demo/reset")
    print(f"\n{sum(results)}/{len(results)} passed" + ("" if all(results) else "  -- SOME FAILED"))


asyncio.run(main())
