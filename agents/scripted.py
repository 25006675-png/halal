r"""
HalalReady scripted agents: the demo run with fixed answers and timing, no Gemini.

    .venv\Scripts\python -m agents.scripted

Works off the same task board and /agent endpoints as agents/runner.py, so the
dashboard shows it exactly like a live run. What each file "says" comes from
demo_case/case.json (scripts/make_demo_case.py). The run:

  1. Coordinator sorts the files, reads the lists and proposes a plan.
  2. On approval, Certificate Checker, On-site Inspector and Document Writer
     work in parallel.
  3. The expired oil certificate pauses the whole run until the owner chooses
     how to contact Minyak Murni; Supplier Chaser drafts the message and the
     run resumes once it is sent (or the owner chooses "Not now").
  4. The store photo shows an undeclared oil brand; the Inspector asks for a
     new photo (it does not pause the run).
  5. When the three are done, the Coordinator builds the pack and Renewal
     Watch sets reminders.
  6. Follow-ups from the output checklist (a renewed certificate, a new store
     photo) are checked and the pack is updated.
"""

import asyncio
import json
import logging
import os
import random
import re
import sys
import time
from datetime import date
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
BUSINESS_ID = int(os.getenv("BUSINESS_ID", "1"))
TOKEN = os.getenv("CONNECTOR_TOKEN") or ""
HEARTBEAT = ROOT / ".cache" / "runner.json"
PACE = float(os.getenv("DEMO_PACE", "1.8"))   # stretches every thinking pause; 1.8 gives about 1:45 of agent work
# Presenter steps: the run holds before each reveal until the presenter presses the right arrow (POST /demo/next).
#   1: the Coordinator's plan   2: the expired certificate   3: the Inspector's findings
# A press before the hold is reached skips the waiting on the way there. DEMO_STEPS=0 plays straight through.
STEPS = os.getenv("DEMO_STEPS", "1") != "0"
CASE = json.loads((ROOT / "demo_case" / "case.json").read_text(encoding="utf-8"))

log = logging.getLogger("scripted")

PLAN = [
    ("certificate_checker", "Check every ingredient and supplier certificate",
     "Here are 6 ingredients and 5 supplier certificates. Can you check each one?"),
    ("onsite_inspector", "Check the zone photos",
     "Here are the 5 zone photos. Can you check each zone against the halal requirements?"),
    ("document_writer", "Draft the halal policy and procedures",
     "Can you draft the halal policy, ingredient control and traceability procedures from her files?"),
]
CHANNEL_NAME = {"whatsapp": "WhatsApp", "telegram": "Telegram", "email": "email"}


def nice(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%b %Y')}"


class Run:
    def __init__(self):
        headers = {"X-Connector-Token": TOKEN} if TOKEN else {}
        self.http = httpx.AsyncClient(base_url=BACKEND_URL, headers=headers, timeout=30)
        self.rnd = random.Random(7)
        self.resume = asyncio.Event()
        self.resume.set()
        self.handled: set[str] = set()   # id + creation time: ids start again after a reset
        self.main_done: set[str] = set()
        self.pack_built = False
        self.active: set[str] = set()   # agents mid-way through their main task
        self.workers: set[asyncio.Task] = set()
        self.run_sig = None              # the first task of the current run; changes when the case is reset
        self.presses = None              # the presenter's right-arrow count when we last looked
        self.allowed = 0                 # holds the presenter has released
        self.next_hold = 1               # the next hold on the way
        self.owner_busy = False          # a decision is open (plan, blocker): presses are ignored

    # ── backend ──────────────────────────────────────────────────────
    async def call(self, method: str, path: str, body: dict | None = None, params: dict | None = None,
                   data: dict | None = None):
        if body is not None:
            body = {k: v for k, v in body.items() if v is not None}
        r = await self.http.request(method, path, json=body, params=params, data=data)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path}: {r.status_code} {r.text[:200]}")
        return r.json()

    async def event(self, agent: str, label: str, status: str = "info", message: str | None = None,
                    handed_to: str | None = None):
        await self.call("POST", "/agent/events", {"business_id": BUSINESS_ID, "agent": agent, "label": label[:120],
                                                  "status": status, "message": message, "handed_to": handed_to})

    async def task(self, sender: str, assignee: str, title: str, message: str, payload: dict | None = None):
        return await self.call("POST", "/agent/tasks", {"business_id": BUSINESS_ID, "from_agent": sender,
                                                        "assignee": assignee, "title": title, "message": message,
                                                        "payload": payload})

    async def complete(self, task: dict, result: str, reply: str | None = None):
        await self.call("POST", f"/agent/tasks/{task['id']}/complete",
                        {"agent": task["assignee"], "result": result, "reply": reply})

    async def pick(self, agent: str):
        await self.call("GET", "/agent/tasks", params={"agent": agent, "business_id": BUSINESS_ID})

    async def files(self) -> list[dict]:
        return await self.call("GET", "/agent/files", params={"business_id": BUSINESS_ID})

    async def ingredients(self) -> dict[str, dict]:
        rows = (await self.call("GET", "/agent/certificates", params={"business_id": BUSINESS_ID}))["ingredients"]
        return {r["name"]: r for r in rows}

    async def today(self) -> date:
        return date.fromisoformat((await self.call("GET", "/clock"))["today"])

    # ── time: thinking pauses, and the run-wide pause at a blocker ───
    async def think(self, seconds: float, pausable: bool = True):
        left = seconds * PACE * self.rnd.uniform(0.85, 1.15)
        while left > 0:
            if pausable and not self.resume.is_set():
                await self.resume.wait()
            if pausable and STEPS and self.allowed >= self.next_hold:
                return
            step = min(0.2, left)
            await asyncio.sleep(step)
            left -= step

    async def hold(self, n: int):
        """Wait here until the presenter presses the right arrow for step n."""
        if not STEPS:
            return
        while self.allowed < n:
            await asyncio.sleep(0.2)
        self.next_hold = max(self.next_hold, n + 1)   # steps are released strictly in order: 1, 2, 3

    async def read_presses(self):
        try:
            n = (await self.call("GET", "/demo/next"))["count"]
        except Exception:
            return
        if self.presses is None:
            self.presses = n
        for _ in range(max(0, n - self.presses)):
            # one press releases the next hold; none while a decision is open, and they never pile up
            if not self.owner_busy and self.resume.is_set() and self.allowed < self.next_hold:
                self.allowed = self.next_hold
                log.info("Presenter: step %d", self.allowed)
        self.presses = n

    # ── the board ────────────────────────────────────────────────────
    async def loop(self):
        log.info("Scripted agents up, backend %s", BACKEND_URL)
        while True:
            self.heartbeat()
            try:
                every = await self.call("GET", f"/business/{BUSINESS_ID}/tasks")
            except Exception as exc:
                log.warning("Backend not reachable: %s", exc)
                await asyncio.sleep(2)
                continue
            # The case was reset (the first task is gone or new): stop everything from the old run.
            first = min(every, key=lambda t: t["id"]) if every else None
            sig = (first["id"], first["created_at"]) if first else None
            if sig != self.run_sig:
                if self.run_sig is not None:
                    self.forget()
                self.run_sig = sig
            tasks = [t for t in every if t["status"] != "done"]
            await self.read_presses()
            for t in sorted(tasks, key=lambda t: t["id"]):
                key = f"{t['id']}:{t['created_at']}"
                if key in self.handled:
                    continue
                handler = self.route(t)
                if handler:
                    self.handled.add(key)
                    w = asyncio.create_task(self.guard(handler, t))
                    self.workers.add(w)
                    w.add_done_callback(self.workers.discard)
            await asyncio.sleep(0.5)

    def forget(self):
        log.info("The case was reset; stopping %d agent task(s) from the old run", len(self.workers))
        for w in list(self.workers):
            w.cancel()
        self.workers.clear()
        self.main_done.clear()
        self.active.clear()
        self.pack_built = False
        self.resume.set()
        self.allowed, self.next_hold, self.owner_busy = 0, 1, False

    def heartbeat(self):
        try:
            HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
            HEARTBEAT.write_text(json.dumps({"at": time.time(), "pid": os.getpid(), "model": "HalalReady agents",
                                             "keys": 1, "error": None}), encoding="utf-8")
        except OSError:
            pass

    async def guard(self, handler, task: dict):
        try:
            await self.pick(task["assignee"])
            await handler(task)
        except asyncio.CancelledError:
            log.info("%s stopped: the case was reset", handler.__name__)
        except Exception:
            log.exception("%s failed on task %s", handler.__name__, task["id"])

    def route(self, t: dict):
        who, title = t["assignee"], t["title"]
        if who == "coordinator":
            if title.startswith("Owner asked for changes"):
                return self.coord_replan
            if t["from_agent"] == "owner":
                return self.coord_start
        if who == "certificate_checker":
            if title.startswith("Check every"):
                return self.checker_run
            if title.startswith("Owner answered"):
                return self.checker_answer
            if title.startswith(("Owner uploaded a certificate", "Check new certificate")):
                return self.checker_follow_up
        if who == "supplier_chaser" and title.startswith("Ask "):
            return self.chaser_draft
        if who == "onsite_inspector":
            if title.startswith("Check the zone"):
                return self.inspector_run
            if title.startswith(("Owner answered", "Owner uploaded a new photo")):
                return self.inspector_follow_up
        if who == "document_writer" and title.startswith("Draft"):
            return self.writer_run
        if who == "renewal_watch" and title.startswith("Watch"):
            return self.renewal_run
        return None

    # ── Coordinator ──────────────────────────────────────────────────
    async def coord_start(self, task: dict):
        # A new instruction is a new run: forget the last one.
        self.main_done.clear()
        self.active.clear()
        self.pack_built = False
        self.resume.set()
        files = await self.files()
        known = {f["filename"]: f for f in CASE["files"]}
        await self.event("coordinator", f"On it: Reading your {len(files)} files", "action")
        await self.think(1.2)
        await self.event("coordinator", f"Opening {len(files)} files", "action",
                         message="Checking each file is what its name says, readable and complete.")
        trays: dict[str, int] = {}
        for f in files:
            info = known.get(f["filename"]) or self.guess(f["filename"])
            await self.call("POST", f"/agent/files/{f['id']}/sort", {
                "category": info["category"], "kind": info["kind"], "zone": info.get("zone"), "agent": "coordinator"})
            trays[info["category"]] = trays.get(info["category"], 0) + 1
            await self.think(0.3)
        await self.event("coordinator", f"Sorted {len(files)} files into {len(trays)} trays", "ok",
                         message=", ".join(f"{n} {c}" for c, n in trays.items()))
        await self.think(1.0)
        await self.event("coordinator", "Reading 03 Ingredient list", "action")
        await self.think(1.6)
        await self.event("coordinator", "Found 6 ingredients in 2 products", "ok",
                         message="Sambal Tumis and Sambal Ikan Bilis: dried chilli, cooking oil, shallot paste, "
                                 "garlic paste, sugar and ikan bilis.")
        await self.event("coordinator", "Reading 04 Supplier list", "action")
        await self.think(1.2)
        await self.event("coordinator", "5 approved suppliers, each with a certificate", "ok")
        await self.think(0.8)
        await self.event("coordinator", "Planning the run", "action")
        await self.think(2.0)
        await self.hold(1)
        await self.propose()
        await self.complete(task, "Plan proposed")

    async def propose(self, note: str | None = None):
        self.owner_busy = True
        summary = ("I sorted your 16 files: 2 products, 6 ingredients, 5 suppliers and 5 zone photos. Three agents "
                   "will work in parallel on the certificates, the premises photos and your halal documents. "
                   "I will stop and ask you if anything needs your decision.")
        if note:
            summary += f" Your note is included: “{note}”."
        await self.call("POST", "/agent/approvals", {
            "business_id": BUSINESS_ID, "kind": "plan", "agent": "coordinator", "title": "Approve the plan",
            "body_en": summary,
            "plan": [{"assignee": a, "title": t, "message": m, "detail": note} for a, t, m in PLAN]})

    async def coord_replan(self, task: dict):
        note = (task.get("detail") or "").strip()
        await self.event("coordinator", "On it: Updating the plan", "action")
        await self.think(2.5, pausable=False)
        await self.event("coordinator", "Updated the plan", "ok",
                         message=f"Noted: “{note}”." if note else "Same plan, ready again.")
        await self.propose(note or None)
        await self.complete(task, "Plan updated")

    async def coord_pack(self):
        self.pack_built = True
        await self.event("coordinator", "On it: Building your application pack", "action")
        await self.think(2.5)
        readiness = (await self.call("GET", "/agent/case", params={"business_id": BUSINESS_ID}))["readiness"]
        await self.call("POST", "/agent/status", {"business_id": BUSINESS_ID, "sentence":
                        f"{readiness['score']}% ready. Cooking oil needs Minyak Murni's renewed certificate, the "
                        "cleaning area needs a new photo, and 3 documents are waiting for your approval."})
        pack = await self.call("POST", "/agent/pack", params={"business_id": BUSINESS_ID})
        await self.event("coordinator", f"Application pack ready: {pack['items_ready']} of {pack['items_total']} items",
                         "ok", message="The open items are highlighted on your checklist, each with what to do next.")
        await self.think(1.5)
        await self.task("coordinator", "renewal_watch", "Watch certificate expiry dates",
                        "The pack is built. Can you keep an eye on every certificate's expiry date from now on?")

    async def coord_update_pack(self, why: str):
        if not self.pack_built:
            return
        await self.think(1.5, pausable=False)
        pack = await self.call("POST", "/agent/pack", params={"business_id": BUSINESS_ID})
        await self.event("coordinator", "Updated your application pack", "ok",
                         message=f"{why} {pack['items_ready']} of {pack['items_total']} items are ready.")

    async def main_task_done(self, agent: str):
        self.main_done.add(agent)
        if {"certificate_checker", "onsite_inspector", "document_writer"} <= self.main_done and not self.pack_built:
            await self.coord_pack()

    def guess(self, name: str) -> dict:
        n = name.lower()
        if re.search(r"photo|\.(jpe?g|png|heic)$", n) and "cert" not in n:
            zone = next((z for z in CASE["zones"] if z in n), "store")
            return {"category": "site", "kind": "photo", "zone": zone}
        if "cert" in n or "sijil" in n:
            return {"category": "suppliers", "kind": "certificate"}
        if re.search(r"recipe|resipi|ingredient|label", n):
            return {"category": "products", "kind": "recipe" if "recipe" in n else "other"}
        if "supplier" in n or "invoice" in n:
            return {"category": "suppliers", "kind": "other"}
        return {"category": "company", "kind": "other"}

    # ── Certificate Checker ──────────────────────────────────────────
    def checks(self, c: dict, today: date) -> list[dict]:
        days = (date.fromisoformat(c["expiry_iso"]) - today).days
        names = " and ".join(i.lower() for i in c["ingredients"])
        b = c["boxes"]
        return [
            {"key": "type", "label": "It’s a halal certificate, not an invoice or a product photo", "ok": True,
             "detail": "Sijil Pengesahan Halal", "box": b["title"]},
            {"key": "holder", "label": f"Company name matches {c['supplier']}", "ok": c["holder"] == c["supplier"],
             "detail": c["holder"], "box": b["holder"]},
            {"key": "product", "label": f"Covers the right product: {names}", "ok": True,
             "detail": "; ".join(c["products"]), "box": b["products"]},
            {"key": "issuer", "label": "Issued by a recognised body", "ok": True, "detail": c["issuer"], "box": b["issuer"]},
            {"key": "expiry", "ok": days >= 0, "box": b["expiry"],
             "label": f"Valid until {c['expiry']}" if days >= 0 else f"Expired on {c['expiry']}, {-days} days ago",
             "detail": f"Days counted by HalalReady from today, {nice(today.isoformat())}, not by the AI"},
        ]

    async def record(self, c: dict, file_id: int, ings: dict[str, dict], today: date) -> tuple[list[dict], int]:
        checks = self.checks(c, today)
        for name in c["ingredients"]:
            await self.call("POST", "/agent/certificates", {
                "business_id": BUSINESS_ID, "ingredient_id": ings[name]["id"], "file_id": file_id,
                "issuer": c["issuer"], "cert_number": c["number"], "expiry_date": c["expiry_iso"],
                "issuer_recognised": True, "holder": c["holder"], "products": c["products"], "checks": checks})
        return checks, sum(1 for x in checks if x["ok"])

    async def checker_run(self, task: dict):
        self.owner_busy = False   # the plan was approved
        self.active.add("certificate_checker")
        await self.event("certificate_checker", "On it: Checking 6 ingredients and 5 certificates", "action")
        await self.think(1.2)
        await self.event("certificate_checker", "Reading 03 Ingredient list", "action")
        await self.think(1.8)
        sup = {s[0]: s for s in CASE["suppliers"]}
        await self.call("POST", "/agent/ingredients", {"business_id": BUSINESS_ID, "ingredients": [
            {"name": n, "brand": b, "kind": k, "proof_type": "halal_certificate", "supplier_name": s,
             "supplier_contact_name": sup[s][1], "supplier_phone": sup[s][2], "product_names": p}
            for n, b, s, k, p in CASE["ingredients"]]})
        await self.event("certificate_checker", "Saved 6 ingredients with their suppliers", "ok")
        by_name = {f["filename"]: f for f in await self.files()}
        ings, today = await self.ingredients(), await self.today()
        order = ["chilli", "shallot_garlic", "oil", "ikan_bilis", "sugar"]
        certs = sorted(CASE["certificates"], key=lambda c: order.index(c["key"]))
        for c in certs:
            f = by_name.get(c["file"])
            if not f:
                continue
            await self.think(0.8)
            if c["key"] == "oil":
                await self.hold(2)
            await self.event("certificate_checker", "Reading " + Path(c["file"]).stem.replace("_", " "), "action")
            await self.think(1.0 if c["key"] == "oil" else 2.6)
            checks, passed = await self.record(c, f["id"], ings, today)
            what = " and ".join(c["ingredients"])
            what = what[0] + what[1:].lower()
            if passed == len(checks):
                await self.event("certificate_checker", f"{what}: certificate valid", "ok",
                                 message=f"{passed} of {len(checks)} checks passed. Valid until {c['expiry']}.")
                continue
            await self.event("certificate_checker", f"{what}: certificate expired", "problem",
                             message=f"{passed} of {len(checks)} checks passed. {checks[-1]['label']}.")
            await self.blocker(c, f["id"])
        await self.think(1.0)
        await self.event("certificate_checker", "All 6 ingredients checked", "ok",
                         message="5 are covered by a valid certificate. Cooking oil is waiting for Minyak Murni.")
        await self.complete(task, "6 ingredients checked, 1 waiting on a supplier",
                            reply="5 of 6 ingredients are covered. Cooking oil is waiting for Minyak Murni’s "
                                  "renewed certificate.")
        self.active.discard("certificate_checker")
        await self.main_task_done("certificate_checker")

    async def blocker(self, c: dict, file_id: int):
        """The first blocker: the whole run waits for the owner's decision."""
        contact = next(s for s in CASE["suppliers"] if s[0] == c["supplier"])[1]
        self.decided = asyncio.Event()
        await self.call("POST", "/agent/approvals", {
            "business_id": BUSINESS_ID, "kind": "question", "agent": "certificate_checker",
            "title": "Expired certificate: cooking oil (MURNI)", "ingredient_name": c["ingredients"][0],
            "file_id": file_id,
            "body_en": f"{c['supplier']}’s halal certificate {c['number']} expired on {c['expiry']}. JAKIM needs a "
                       f"valid certificate for every ingredient. How should I ask {contact} for the renewed one?",
            "options": [{"key": "whatsapp", "label": "WhatsApp"}, {"key": "telegram", "label": "Telegram"},
                        {"key": "email", "label": "Email"}, {"key": "later", "label": "Not now"}]})
        self.resume.clear()
        for agent in sorted(self.active - {"certificate_checker"}):
            await self.event(agent, "On it: Paused until Mak Teh decides", "action")
        await self.event("coordinator", "Paused the run: needs your decision", "attention",
                         message="Minyak Murni’s oil certificate has expired. The other agents wait until you "
                                 "choose what to do.")
        await self.decided.wait()

    async def checker_answer(self, task: dict):
        said = (task.get("detail") or "").lower()
        choice = next((k for k in CHANNEL_NAME if k in said), "later")
        c = next(x for x in CASE["certificates"] if x["key"] == "oil")
        contact = next(s for s in CASE["suppliers"] if s[0] == c["supplier"])[1]
        if choice in CHANNEL_NAME:
            await self.task("certificate_checker", "supplier_chaser",
                            f"Ask {c['supplier']} for the renewed oil certificate",
                            f"Minyak Murni’s oil certificate expired on {c['expiry']}. Can you draft "
                            f"{'an' if choice == 'email' else 'a'} {CHANNEL_NAME[choice]} to {contact} asking for the "
                            "renewed one?",
                            payload={"channel": choice, "supplier_name": c["supplier"], "ingredient_name": "Cooking oil"})
            await self.complete(task, f"Owner chose {choice}", reply="Handed to the Supplier Chaser.")
        else:
            await self.complete(task, "Owner chose to wait")
            await self.resume_run("Cooking oil stays open on your checklist.")

    async def resume_run(self, why: str):
        await self.event("coordinator", "Resumed the run", "ok", message=why)
        self.resume.set()
        if getattr(self, "decided", None):
            self.decided.set()

    async def checker_follow_up(self, task: dict):
        p = task.get("payload") or {}
        file_id = (p.get("file_ids") or [None])[0]
        c = CASE["renewed_certificate"]
        await self.event("certificate_checker", "On it: Checking the new certificate", "action")
        await self.think(1.0, pausable=False)
        f = next((x for x in await self.files() if x["id"] == file_id), None)
        await self.event("certificate_checker", "Reading " + Path(f["filename"] if f else c["file"]).stem.replace("_", " "),
                         "action")
        await self.think(2.8, pausable=False)
        checks, passed = await self.record(c, file_id, await self.ingredients(), await self.today())
        await self.event("certificate_checker", "Cooking oil: certificate valid", "ok",
                         message=f"{passed} of {len(checks)} checks passed. Valid until {c['expiry']}.")
        await self.complete(task, "Renewed certificate checked: valid")
        await self.coord_update_pack("Cooking oil is now covered.")

    # ── Supplier Chaser ──────────────────────────────────────────────
    async def chaser_draft(self, task: dict):
        p = task.get("payload") or {}
        channel = p.get("channel") or "whatsapp"
        c = next(x for x in CASE["certificates"] if x["key"] == "oil")
        contact = next(s for s in CASE["suppliers"] if s[0] == c["supplier"])[1]
        await self.event("supplier_chaser", f"On it: Writing the {CHANNEL_NAME[channel]} to {contact}", "action")
        await asyncio.sleep(2.6)   # with the board polling, the draft shows about 3.5 s after the owner's choice
        if channel == "email":
            ms = (f"Subject: Sijil halal minyak masak MURNI yang baharu\n\nAssalamualaikum {contact},\n\n"
                  f"Saya Mak Teh dari Mak Teh Sambal Sdn Bhd. Sijil halal minyak masak sawit MURNI ({c['number']}) "
                  f"telah tamat tempoh pada {c['expiry']}. Kami sedang menyediakan permohonan pensijilan halal. "
                  "Boleh puan hantarkan salinan sijil yang baharu?\n\nTerima kasih,\nMak Teh\nMak Teh Sambal Sdn Bhd")
            en = (f"Subject: Renewed halal certificate for MURNI cooking oil\n\nAssalamualaikum {contact},\n\n"
                  f"This is Mak Teh from Mak Teh Sambal Sdn Bhd. The halal certificate for MURNI palm cooking oil "
                  f"({c['number']}) expired on {c['expiry']}. We are preparing our halal certification application. "
                  "Could you send us a copy of the renewed certificate?\n\nThank you,\nMak Teh\nMak Teh Sambal Sdn Bhd")
        else:
            ms = (f"Assalamualaikum {contact}, ini Mak Teh dari Mak Teh Sambal. Sijil halal minyak masak MURNI "
                  f"({c['number']}) dah tamat pada {c['expiry']}. Boleh hantar sijil yang baharu? Kami nak hantar "
                  "permohonan halal minggu ini. Terima kasih!")
            en = (f"Assalamualaikum {contact}, this is Mak Teh from Mak Teh Sambal. The halal certificate for MURNI "
                  f"cooking oil ({c['number']}) expired on {c['expiry']}. Could you send the renewed one? We want to "
                  "submit our halal application this week. Thank you!")
        a = await self.call("POST", "/agent/approvals", {
            "business_id": BUSINESS_ID, "kind": "message", "agent": "supplier_chaser", "supplier_name": c["supplier"],
            "ingredient_name": "Cooking oil", "channel": channel, "body_ms": ms, "body_en": en,
            "title": f"Message to {c['supplier']} about cooking oil"})
        while True:
            rows = await self.call("GET", f"/business/{BUSINESS_ID}/approvals")
            st = next((r["status"] for r in rows if r["id"] == a["id"]), "pending")
            if st not in ("pending", "approved"):
                break
            await asyncio.sleep(0.5)
        paused = not self.resume.is_set()
        if st in ("sent", "replied"):
            await self.complete(task, "Message sent", reply=f"Sent to {contact}. I’ll pass on her reply when it comes.")
            await self.think(1.0, pausable=False)
            if paused:
                await self.resume_run(f"The message to {contact} is sent. Back to work.")
        else:
            await self.complete(task, "Owner did not send the message")
            if paused:
                await self.resume_run("Cooking oil stays open on your checklist.")

    # ── On-site Inspector ────────────────────────────────────────────
    async def zone_photo(self, zone: str) -> dict | None:
        return next((f for f in reversed(await self.files()) if f["zone"] == zone), None)

    async def inspector_run(self, task: dict):
        self.active.add("onsite_inspector")
        await self.event("onsite_inspector", f"On it: Checking {len(CASE['zones'])} zones", "action")
        await self.think(1.5)
        for zone in ["processing", "packing", "store", "waste", "cleaning"]:
            z = CASE["zones"][zone]
            if zone == "cleaning":
                await self.hold(3)
            k = 0.3 if STEPS and zone == "cleaning" else 1   # after step 3: the finding, quickly
            photo = await self.zone_photo(zone)
            await self.think(0.8 * k)
            if not photo:
                await self.event("onsite_inspector", f"Looking for a {z['title'].lower()} photo", "action")
                await self.think(1.6 * k)
                await self.call("POST", "/agent/site-findings", {
                    "business_id": BUSINESS_ID, "zone": zone, "severity": "attention", "title": "No photo yet",
                    "checks": z["checks"], "suggestion": z["suggestion"]})
                await self.event("onsite_inspector", f"{zone.title()}: no photo yet", "attention",
                                 message=z["checks"][0]["detail"])
                await self.call("POST", "/agent/approvals", {
                    "business_id": BUSINESS_ID, "kind": "question", "agent": "onsite_inspector",
                    "title": f"Photo needed: {z['title'].lower()}", "zone": zone, "body_en": z["suggestion"]})
                continue
            await self.event("onsite_inspector", "Reading " + Path(photo["filename"]).stem.replace("_", " "), "action")
            await self.think(3.4 * k)
            fix = [c for c in z["checks"] if c["state"] != "ok"]
            if not fix:
                await self.call("POST", "/agent/site-findings", {
                    "business_id": BUSINESS_ID, "zone": zone, "severity": "ok", "title": "All checks passed",
                    "checks": z["checks"], "photo_file_id": photo["id"]})
                await self.event("onsite_inspector", f"{zone.title()}: " + ", ".join(c["label"].lower() for c in z["checks"]), "ok")
                continue
            await self.call("POST", "/agent/site-findings", {
                "business_id": BUSINESS_ID, "zone": zone, "severity": "attention", "title": fix[0]["label"],
                "detail": fix[0]["detail"], "checks": z["checks"], "suggestion": z["suggestion"], "photo_file_id": photo["id"]})
            await self.event("onsite_inspector", f"{zone.title()}: {fix[0]['label'].lower()}", "attention",
                             message=f"{fix[0]['detail']} {fix[0]['ask']}.")
            await self.think(1.2 * k)
            await self.call("POST", "/agent/approvals", {
                "business_id": BUSINESS_ID, "kind": "question", "agent": "onsite_inspector",
                "title": f"New photo needed: {z['title'].lower()}", "file_id": photo["id"], "zone": zone,
                "body_en": z["suggestion"]})
        n = len(CASE["zones"])
        await self.complete(task, f"{n} zones checked, 1 needs you",
                            reply=f"{n - 1} of {n} zones are fine. Cleaning area: detergent next to food, I asked Mak Teh "
                                  "to move it and send a new photo.")
        self.active.discard("onsite_inspector")
        await self.main_task_done("onsite_inspector")

    async def inspector_follow_up(self, task: dict):
        p = task.get("payload") or {}
        file_ids = p.get("file_ids") or []
        zone = p.get("zone")
        if not zone:   # an answer on a question card: the zone is on the question
            a = next((x for x in await self.call("GET", f"/business/{BUSINESS_ID}/approvals")
                      if x["id"] == p.get("approval_id")), None)
            zone = (json.loads(a["payload"]) if a and a.get("payload") else {}).get("zone") or "store"
        z = CASE["zones"][zone]
        if not file_ids:
            await self.complete(task, "No photo yet")
            await self.event("onsite_inspector", f"{zone.title()}: still needs a photo", "attention",
                             message="Thanks. I can only clear it once I see a photo.")
            return
        await self.call("POST", f"/agent/files/{file_ids[0]}/sort",
                        {"category": "site", "kind": "photo", "zone": zone, "agent": "onsite_inspector"})
        await self.event("onsite_inspector", f"On it: Checking the new {z['title'].lower()} photo", "action")
        await self.think(1.0, pausable=False)
        f = next((x for x in await self.files() if x["id"] == file_ids[0]), {"filename": "new photo"})
        await self.event("onsite_inspector", "Reading " + Path(f["filename"]).stem.replace("_", " "), "action")
        await self.think(3.2, pausable=False)
        site = await self.call("GET", f"/business/{BUSINESS_ID}/site")
        for finding in next(x for x in site["zones"] if x["zone"] == zone)["findings"]:
            if finding["status"] == "open" and finding["severity"] != "ok":
                await self.call("PATCH", f"/site-findings/{finding['id']}", {"status": "resolved"})
        checks = z.get("after") or [dict(c, state="ok") for c in z["checks"]]
        await self.call("POST", "/agent/site-findings", {
            "business_id": BUSINESS_ID, "zone": zone, "severity": "ok", "title": "All checks passed after the fix",
            "checks": checks, "photo_file_id": file_ids[0]})
        await self.event("onsite_inspector", f"{zone.title()}: " + ", ".join(c["label"].lower() for c in checks), "ok",
                         message=f"{z['title']} is clear now.")
        await self.complete(task, f"{zone} re-checked: clear")
        await self.coord_update_pack(f"The {z['title'].lower()} is clear now.")

    # ── Document Writer ──────────────────────────────────────────────
    async def writer_run(self, task: dict):
        self.active.add("document_writer")
        await self.event("document_writer", "On it: Drafting 3 halal documents", "action")
        for doc_type, d in CASE["documents"].items():
            await self.think(1.5)
            await self.event("document_writer", f"Writing the {d['title']}", "action")
            await self.think(5.5)
            doc = await self.call("POST", "/agent/documents", {"business_id": BUSINESS_ID, "doc_type": doc_type,
                                                               "title": d["title"], "body": d["body"]})
            await self.event("document_writer", f"Drafted {doc['title']} v{doc['version']}", "ok")
            await self.think(1.2)
            n = len(re.findall(r"(?m)^## ", d["body"]))
            await self.event("document_writer", "Checked against JAKIM’s required sections", "ok",
                             message=f"{d['title']}: all {n} required sections are in.")
            await self.call("POST", "/agent/approvals", {"business_id": BUSINESS_ID, "kind": "document",
                                                         "agent": "document_writer", "doc_type": doc_type})
        await self.complete(task, "3 documents drafted and checked",
                            reply="3 documents are drafted and checked. They wait for Mak Teh’s approval on the "
                                  "checklist.")
        self.active.discard("document_writer")
        await self.main_task_done("document_writer")

    # ── Renewal Watch ────────────────────────────────────────────────
    async def renewal_run(self, task: dict):
        await self.event("renewal_watch", "On it: Setting renewal reminders", "action")
        await self.think(2.0)
        await self.event("renewal_watch", "Reminder set: shallot and garlic paste", "info",
                         message="Bawang Segar’s certificate expires on 28 Feb 2027. I’ll draft a renewal request on "
                                 "30 Dec 2026, 60 days before.")
        await self.think(1.2)
        await self.event("renewal_watch", "Watching 5 certificates for expiry", "ok",
                         message="Next after that: sugar on 31 Mar 2027 and dried chilli on 31 Aug 2027.")
        await self.complete(task, "Reminders set", reply="Done. I’ll wake up 60 days before each certificate expires.")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(Run().loop())


if __name__ == "__main__":
    main()
