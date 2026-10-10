r"""
Demo control for the Mak Teh Sambal case. The backend must be running
(uvicorn backend.app:app --port 8000); `verify` starts one if it isn't.

    .venv\Scripts\python scripts/demo.py reset          # empty database, date 15 Oct 2026
    .venv\Scripts\python scripts/demo.py drop           # owner drops the pile and gives the one instruction
    .venv\Scripts\python scripts/demo.py plan           # owner approves the Coordinator's plan
    .venv\Scripts\python scripts/demo.py approve        # approve every pending supplier message
    .venv\Scripts\python scripts/demo.py reply          # supplier replies with the oil certificate (stage fallback)
    .venv\Scripts\python scripts/demo.py answer         # owner uploads the clear ikan bilis copy
    .venv\Scripts\python scripts/demo.py check          # compare the current state with the answer key
    .venv\Scripts\python scripts/demo.py verify --runs 3 [--no-cache]   # whole scenario, N times, with agents
    .venv\Scripts\python scripts/demo.py snapshot save NAME | restore NAME | list

The agents run separately (python -m agents.runner), except in `verify`.
"""

import argparse
import asyncio
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

BACKEND = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
BIZ = int(os.getenv("BUSINESS_ID", "1"))
PILE = ROOT / "sample_case" / "pile"
KEPT = ROOT / "sample_case" / "kept_back"
DEMO_DAY = "2026-10-15"
INSTRUCTION = "Prepare Mak Teh Sambal's halal certification application."
SNAPSHOTS = ROOT / "snapshots"


def _resolve(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (ROOT / path).resolve()


DB_PATH = _resolve(os.getenv("DATABASE_PATH", "./backend/halalready.db"))
UPLOAD_DIR = _resolve(os.getenv("UPLOAD_DIR", "./backend/uploads"))

http = httpx.Client(base_url=BACKEND, timeout=60)


def api(method: str, path: str, **kw):
    r = http.request(method, path, **kw)
    if r.status_code >= 400:
        raise SystemExit(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
    return r.json()


# ── steps ────────────────────────────────────────────────────────────

def _check_ours():
    """Never reset someone else's server that happens to sit on the same port."""
    try:
        title = http.get("/openapi.json").json().get("info", {}).get("title")
    except (httpx.HTTPError, ValueError):
        title = None
    if title != "HalalReady backend":
        raise SystemExit(f"{BACKEND} is not this HalalReady backend (title: {title}). Set BACKEND_URL in .env.")


def reset():
    _check_ours()
    api("POST", "/admin/reset")
    api("PUT", "/clock", json={"today": DEMO_DAY, "business_id": BIZ})
    print(f"Reset. Today is {DEMO_DAY}.")


def drop():
    files = sorted(PILE.glob("*"))
    if not files:
        raise SystemExit("No sample files. Run scripts/make_sample_case.py first.")
    handles = [("files", (f.name, f.open("rb"), "image/png" if f.suffix == ".png" else "application/pdf"))
               for f in files]
    try:
        api("POST", f"/business/{BIZ}/files", files=handles)
    finally:
        for _, (_, fh, _) in handles:
            fh.close()
    run = api("POST", f"/business/{BIZ}/runs", json={"mode": "prepare", "instruction": INSTRUCTION})
    print(f"Dropped {len(files)} files; run {run['id']} started: {INSTRUCTION}")


def plan():
    pending = [a for a in api("GET", f"/business/{BIZ}/approvals", params={"status": "pending"}) if a["kind"] == "plan"]
    if not pending:
        raise SystemExit("No plan is waiting for approval.")
    api("POST", f"/approvals/{pending[0]['id']}/approve", json={})
    print("Plan approved; the tasks have started.")


def approve():
    pending = [a for a in api("GET", f"/business/{BIZ}/approvals", params={"status": "pending"})
               if a["kind"] == "message"]
    for a in pending:
        r = api("POST", f"/approvals/{a['id']}/approve", json={})
        print(f"Approved #{a['id']} {a['title']} -> {r['status']} via {r['channel']}")
    if not pending:
        print("No pending supplier messages.")


def reply():
    sent = [a for a in api("GET", f"/business/{BIZ}/approvals")
            if a["kind"] == "message" and a["status"] == "sent"]
    suppliers = {s["id"]: s["name"] for s in api("GET", f"/business/{BIZ}/suppliers")}
    target = next((a for a in sent if "murni" in suppliers.get(a["supplier_id"], "").lower()), None)
    if not target:
        raise SystemExit("No sent message to Minyak Murni yet. Approve it first.")
    f = KEPT / "reply_certificate_minyak_murni.png"
    with f.open("rb") as fh:
        r = api("POST", f"/approvals/{target['id']}/simulate-reply",
                data={"text": "Salam Mak Teh, ini sijil halal minyak masak kami. Terima kasih."},
                files=[("files", (f.name, fh, "image/png"))])
    print(f"Minyak Murni replied with the certificate (task {r['task_id']}).")


def answer():
    pending = [a for a in api("GET", f"/business/{BIZ}/approvals", params={"status": "pending"})
               if a["kind"] == "question" and "clearer" in a["title"].lower()]
    if not pending:
        raise SystemExit("No 'clearer copy' question is waiting.")
    f = KEPT / "clear_copy_certificate_hasil_laut.png"
    with f.open("rb") as fh:
        r = api("POST", f"/approvals/{pending[0]['id']}/answer", data={"text": "Here is a clearer copy."},
                files=[("files", (f.name, fh, "image/png"))])
    print(f"Owner sent the clear copy (task {r['task_id']}).")


# ── the answer key ───────────────────────────────────────────────────

def _state() -> dict:
    return {
        "files": api("GET", f"/business/{BIZ}/files"),
        "ingredients": api("GET", f"/business/{BIZ}/ingredients"),
        "suppliers": api("GET", f"/business/{BIZ}/suppliers"),
        "site": api("GET", f"/business/{BIZ}/site")["zones"],
        "approvals": api("GET", f"/business/{BIZ}/approvals"),
        "tasks": api("GET", f"/business/{BIZ}/tasks"),
        "events": api("GET", f"/business/{BIZ}/events"),
        "documents": api("GET", f"/business/{BIZ}/documents"),
        "overview": api("GET", f"/business/{BIZ}/overview"),
    }


def _ing(s: dict, brand: str, source: str = "declared") -> dict | None:
    return next((i for i in s["ingredients"] if brand in (i["brand"] or "").upper() and i["source"] == source), None)


def check(stage: int, quiet: bool = False) -> list[tuple[str, bool, str]]:
    """stage 1: after the first run. 2: after the oil reply. 3: after the clear copy."""
    s = _state()
    sup = {x["id"]: x["name"] for x in s["suppliers"]}
    results = []

    def ok(name, cond, info=""):
        results.append((name, bool(cond), info))

    files = s["files"]
    zones_expected = {"11": "store", "12": "processing", "13": "packing", "14": "cleaning", "15": "waste"}
    ok("sorted: every file in a tray", files and all(f["category"] for f in files),
       f"{sum(1 for f in files if not f['category'])} unsorted")
    inv = next((f for f in files if "invoice" in f["filename"]), None)
    ok("sorted: oil invoice under Suppliers", inv and inv["category"] == "suppliers", inv and inv["category"])
    wrong = [f["filename"] for f in files if f["filename"][:2] in zones_expected
             and (f["category"] != "site" or f["zone"] != zones_expected[f["filename"][:2]])]
    ok("sorted: 5 photos in the right zones", not wrong, ", ".join(wrong))

    declared = [i for i in s["ingredients"] if i["source"] == "declared"]
    ok("ingredients: 6 declared, each with a brand", len(declared) == 6 and all(i["brand"] for i in declared),
       ", ".join(f"{i['name']} [{i['brand']}]" for i in declared))

    # 1. waiting on a supplier
    oil = _ing(s, "MURNI")
    oil_msgs = [a for a in s["approvals"] if a["kind"] == "message" and oil and a["ingredient_id"] == oil["id"]]
    if stage == 1:
        ok("1 supplier: cooking oil shows missing", oil and oil["status"] == "missing", oil and oil["status"])
        ok("1 supplier: message to Minyak Murni waits for approval",
           any(a["status"] == "pending" and "murni" in sup.get(a["supplier_id"], "").lower() for a in oil_msgs),
           f"{len(oil_msgs)} message(s)")
        m = next((a for a in oil_msgs if a["status"] == "pending"), None)
        ok("1 supplier: message has Malay and English text", m and m["body_ms"] and m["body_en"])
    else:
        ok("1 supplier: oil reply recorded", any(a["status"] == "replied" for a in oil_msgs))
        ok("1 supplier: cooking oil now valid", oil and oil["status"] == "valid", oil and oil["status"])

    # 2. not sure
    bilis = _ing(s, "HASIL LAUT")
    qs = [a for a in s["approvals"] if a["kind"] == "question" and bilis and a["ingredient_id"] == bilis["id"]]
    if stage < 3:
        ok("2 unsure: ikan bilis shows unclear", bilis and bilis["status"] == "unclear", bilis and bilis["status"])
        ok("2 unsure: nothing guessed from the blurry scan",
           bilis and not bilis["cert_number"] and not bilis["expiry_date"], bilis and bilis["expiry_date"])
        ok("2 unsure: owner asked for a clearer copy", any(a["status"] == "pending" for a in qs), f"{len(qs)} question(s)")
        ok("2 unsure: no supplier message about it",
           not any(a["kind"] == "message" and bilis and a["ingredient_id"] == bilis["id"] for a in s["approvals"]))
    else:
        ok("2 unsure: ikan bilis now valid", bilis and bilis["status"] == "valid", bilis and bilis["status"])

    # 3. conflict
    store = next(z for z in s["site"] if z["zone"] == "store")
    store_flag = [f for f in store["findings"] if "MERPATI" in (f["title"] + (f["detail"] or "")).upper()
                  and f["severity"] in ("attention", "problem")]
    ok("3 conflict: Inspector flags Cap Merpati Hijau in the store", store_flag and store["status"] == "issue",
       store["status"])
    onsite = _ing(s, "MERPATI", "found_on_site")
    ok("3 conflict: Checker adds it as found on site, no certificate", onsite and onsite["status"] == "missing",
       onsite and onsite["name"])
    ok("3 conflict: handoff Inspector -> Checker",
       any(t["from_agent"] == "onsite_inspector" and t["assignee"] == "certificate_checker"
           and "MERPATI" in t["title"].upper() for t in s["tasks"]))
    ok("3 conflict: both agents post about it", all(
        any(e["agent"] == a and "MERPATI" in e["label"].upper() for e in s["events"])
        for a in ("onsite_inspector", "certificate_checker")))
    ok("3 conflict: owner asked about the undeclared item",
       any(a["kind"] == "question" and "MERPATI" in a["title"].upper() for a in s["approvals"]))

    # no false alarms
    others = [i for i in declared if not any(b in (i["brand"] or "").upper() for b in ("MURNI", "HASIL LAUT"))]
    ok("no false alarms: other 4 ingredients valid", len(others) == 4 and all(i["status"] == "valid" for i in others),
       ", ".join(f"{i['name']}={i['status']}" for i in others))
    clear = [z["zone"] for z in s["site"] if z["zone"] != "store" and z["status"] == "clear"]
    ok("no false alarms: other 4 zones clear", len(clear) == 4,
       ", ".join(f"{z['zone']}={z['status']}" for z in s["site"]))
    msg_to = {sup.get(a["supplier_id"], "?") for a in s["approvals"] if a["kind"] == "message"}
    ok("no false alarms: only Minyak Murni is messaged", msg_to == {"Minyak Murni Sdn Bhd"}, ", ".join(msg_to))
    open_tasks = [t["title"] for t in s["tasks"] if t["status"] != "done"]
    ok("board: every task closed", not open_tasks, "; ".join(open_tasks))
    stopped = [e["label"] for e in s["events"] if "stopped early" in e["label"].lower()]
    ok("board: no agent stopped early", not stopped, "; ".join(stopped))
    failed = [t["title"] for t in s["tasks"] if (t["result"] or "").startswith(("FAILED", "Closed with open problems"))]
    ok("board: no task failed its work check", not failed, "; ".join(failed))
    attention = [a["title"] for a in s["approvals"] if a["title"].startswith("Needs attention")]
    ok("board: nothing needs attention", not attention, "; ".join(attention))

    if stage == 1:
        docs = {d["doc_type"]: d["status"] for d in s["documents"]}
        ok("documents: 3 drafts passed review and wait for approval",
           all(docs.get(t) == "pending_approval" for t in ("halal_policy", "ingredient_control", "traceability")),
           json.dumps(docs))
    ok("status sentence written by the Coordinator", s["overview"]["status_by"] == "coordinator",
       s["overview"]["status_sentence"])

    if not quiet:
        for name, passed, info in results:
            print(f"  {'PASS' if passed else 'FAIL'}  {name}" + (f"   [{info}]" if info and not passed else ""))
        print(f"  status: {s['overview']['status_sentence']}  ({s['overview']['readiness']['score']}%)")
    return results


def moments() -> str:
    """Seconds from the plan approval to each wow moment, from the records' own timestamps."""
    from datetime import datetime
    s = _state()
    ts = lambda iso: datetime.fromisoformat(iso).timestamp()
    plan = next((a for a in s["approvals"] if a["kind"] == "plan" and a["decided_at"]), None)
    if not plan:
        return "no approved plan"
    t0 = ts(plan["decided_at"])
    sup = {x["id"]: x["name"] for x in s["suppliers"]}
    oil = [a for a in s["approvals"] if a["kind"] == "message" and "murni" in sup.get(a["supplier_id"], "").lower()]
    copy = [a for a in s["approvals"] if a["kind"] == "question" and "clearer" in a["title"].lower()]
    store = next(z for z in s["site"] if z["zone"] == "store")["findings"]
    merpati = [f for f in store if "MERPATI" in f["title"].upper()]
    checker = [e for e in s["events"] if e["agent"] == "certificate_checker" and "MERPATI" in e["label"].upper()]
    marks = {"oil message": oil and oil[0]["created_at"], "clearer-copy question": copy and copy[0]["created_at"],
             "Inspector flags Merpati": merpati and merpati[0]["created_at"],
             "Checker confirms Merpati": checker and checker[0]["created_at"]}
    parts = [f"{k} +{ts(v) - t0:.0f}s" if v else f"{k} never" for k, v in marks.items()]
    done = [ts(v) - t0 for v in marks.values() if v]
    last = max(done) if len(done) == len(marks) else None
    return "; ".join(parts) + (f"  ->  all wow moments by +{last:.0f}s" if last is not None else "")


# ── full scenario with the agents ────────────────────────────────────

def _ensure_backend() -> subprocess.Popen | None:
    try:
        http.get("/health").raise_for_status()
        return None
    except httpx.HTTPError:
        pass
    print("Starting the backend...")
    port = str(httpx.URL(BACKEND).port or 8000)
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app:app", "--port", port], cwd=ROOT,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        time.sleep(0.5)
        try:
            http.get("/health").raise_for_status()
            return proc
        except httpx.HTTPError:
            continue
    proc.kill()
    raise SystemExit("Backend did not start")


def _agents_until_quiet():
    from agents import gemini, runner, vision
    gemini._pool = None        # async clients and locks belong to one event loop
    vision._locks.clear()
    t = time.time()
    asyncio.run(runner.run(once=True))
    return f"{time.time() - t:.0f}s, {gemini._pool.sent if gemini._pool else 0} Gemini requests"


def verify(runs: int, no_cache: bool):
    import logging
    if no_cache:
        os.environ["VISION_CACHE"] = "0"
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    proc = _ensure_backend()
    table: dict[str, list[bool]] = {}
    try:
        for n in range(1, runs + 1):
            if no_cache:
                from agents import vision
                vision._memory.clear()
            print(f"\n=== Run {n}/{runs} ===")
            reset()
            drop()
            print(f"agents: sorting and plan {_agents_until_quiet()}")
            plan()
            print(f"agents: first pass {_agents_until_quiet()}")
            print(f"moments after the plan approval: {moments()}")
            results = check(1)
            approve()
            reply()
            print(f"agents: after the oil reply {_agents_until_quiet()}")
            results += [(f"[after reply] {r[0]}", r[1], r[2]) for r in check(2) if r[0].startswith(("1 ", "board"))]
            answer()
            print(f"agents: after the clear copy {_agents_until_quiet()}")
            results += [(f"[after copy] {r[0]}", r[1], r[2]) for r in check(3) if r[0].startswith(("2 ", "board"))]
            for name, passed, _ in results:
                table.setdefault(name, []).append(passed)
            snapshot_save(f"verify_run{n}")
    finally:
        if proc:
            proc.terminate()
    print("\n=== Summary ===")
    worst = 0
    for name, passes in table.items():
        worst = max(worst, len(passes) - sum(passes))
        print(f"  {sum(passes)}/{len(passes)}  {name}")
    print("ALL PASS" if worst == 0 else "SOME CHECKS FAILED")


# ── snapshots (the recorded fallback) ────────────────────────────────

def snapshot_save(name: str):
    target = SNAPSHOTS / name
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(target / "halalready.db")
    src.backup(dst)
    src.close()
    dst.close()
    if UPLOAD_DIR.exists():
        shutil.copytree(UPLOAD_DIR, target / "uploads")
    print(f"Saved snapshot '{name}'.")


def snapshot_restore(name: str):
    source = SNAPSHOTS / name
    if not (source / "halalready.db").exists():
        raise SystemExit(f"No snapshot '{name}'. Saved: " + ", ".join(p.name for p in SNAPSHOTS.glob("*")))
    src = sqlite3.connect(source / "halalready.db")
    dst = sqlite3.connect(DB_PATH)
    src.backup(dst)   # safe while the backend is running
    src.close()
    dst.close()
    shutil.rmtree(UPLOAD_DIR, ignore_errors=True)
    if (source / "uploads").exists():
        shutil.copytree(source / "uploads", UPLOAD_DIR)
    print(f"Restored snapshot '{name}'. Refresh the dashboard.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for c in ("reset", "drop", "plan", "approve", "reply", "answer"):
        sub.add_parser(c)
    c = sub.add_parser("check")
    c.add_argument("--stage", type=int, default=1, choices=[1, 2, 3])
    v = sub.add_parser("verify")
    v.add_argument("--runs", type=int, default=3)
    v.add_argument("--no-cache", action="store_true", help="read every file fresh (true reliability test)")
    s = sub.add_parser("snapshot")
    s.add_argument("action", choices=["save", "restore", "list"])
    s.add_argument("name", nargs="?")
    a = p.parse_args()
    if a.cmd == "check":
        check(a.stage)
    elif a.cmd == "verify":
        verify(a.runs, a.no_cache)
    elif a.cmd == "snapshot":
        if a.action == "list":
            print("\n".join(sorted(x.name for x in SNAPSHOTS.glob("*"))) or "No snapshots.")
        elif not a.name:
            raise SystemExit("Give a snapshot name")
        else:
            (snapshot_save if a.action == "save" else snapshot_restore)(a.name)
    else:
        globals()[a.cmd]()


if __name__ == "__main__":
    main()
