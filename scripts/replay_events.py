"""
HalalReady: fake event replay for dashboard development (Person 1).

Plays the Mak Teh demo story against the backend through the same /agent
endpoints the connector uses, so every tab gets real data, not just events.
All data is fictional.

    python scripts/replay_events.py --reset            # Prepare run, ends at 62% with approvals waiting
    python scripts/replay_events.py --reset --finish   # ...then owner approves, replies arrive, pack is built
    python scripts/replay_events.py --upkeep           # jump the date four months; Renewal Watch wakes
    python scripts/replay_events.py --from-run 3       # re-post the events of a real run (sped up)

    --speed 2       twice as fast (default 1 = about one event a second)
    --instant       no delays
    --backend URL   default http://localhost:8000
"""

import argparse
import sys
import time
from datetime import datetime

import httpx

B = 1  # business id

FILES = [
    ("ssm_registration_SAMPLE.txt", "company", "registration", None),
    ("product_list_SAMPLE.txt", "products", "recipe", None),
    ("recipe_sambal_tumis_SAMPLE.txt", "products", "recipe", None),
    ("invoice_rempah_utara_SAMPLE.txt", "suppliers", "invoice", None),
    ("invoice_pasar_borong_SAMPLE.txt", "suppliers", "invoice", None),
    ("cert_chilli_paste_SAMPLE.txt", "suppliers", "certificate", None),
    ("cert_belacan_SAMPLE.txt", "suppliers", "certificate", None),
    ("photo_store_SAMPLE.txt", "site", "photo", "store"),
    ("photo_processing_SAMPLE.txt", "site", "photo", "processing"),
    ("photo_packing_SAMPLE.txt", "site", "photo", "packing"),
    ("photo_cleaning_SAMPLE.txt", "site", "photo", "cleaning"),
    ("photo_waste_SAMPLE.txt", "site", "photo", "waste"),
]

PRODUCTS = ["Sambal Tumis", "Sambal Belacan", "Sos Cili"]
ALL = PRODUCTS

INGREDIENTS = [
    # name, brand, kind, proof, supplier, products
    ("Chilli paste", "Cap Gajah Merah", "processed", "halal_certificate", "Rempah Utara Trading (sample)", ALL),
    ("Dried chillies", None, "natural", "source_document", "Rempah Utara Trading (sample)", ["Sambal Tumis"]),
    ("Shallots", None, "natural", "source_document", "Pasar Borong Ah Seng (sample)", ALL),
    ("Garlic", None, "natural", "source_document", "Pasar Borong Ah Seng (sample)", ALL),
    ("Belacan (shrimp paste)", "Belacan Melaka", "processed", "halal_certificate", "Belacan Melaka Asli (sample)", ["Sambal Belacan"]),
    ("Cooking oil", "Minyak Seri Pagi", "processed", "halal_certificate", "Pasar Borong Ah Seng (sample)", ALL),
    ("Sugar", "Gula Pantai", "processed", "halal_certificate", "Kedai Runcit Pak Mat (sample)", ALL),
    ("Salt", None, "natural", "source_document", "Kedai Runcit Pak Mat (sample)", ALL),
    ("Tamarind paste", "Asam Pak Long", "processed", "halal_certificate", "Rempah Utara Trading (sample)", ["Sambal Tumis"]),
    ("Vinegar", "Cuka Kilat", "processed", "halal_certificate", "Kedai Runcit Pak Mat (sample)", ["Sos Cili"]),
    ("Anchovies", None, "natural", "source_document", "Pasar Borong Ah Seng (sample)", ["Sambal Tumis"]),
    ("Lemongrass", None, "natural", "source_document", "Pasar Borong Ah Seng (sample)", ["Sambal Tumis"]),
]

CERTS = [
    # ingredient, issuer, number, expiry
    ("Chilli paste", "JAKIM", "SAMPLE-HC-1001", "2026-08-31"),          # expired
    ("Dried chillies", "Supplier declaration", "SAMPLE-SD-01", None),
    ("Shallots", "Supplier declaration", "SAMPLE-SD-02", None),
    ("Garlic", "Supplier declaration", "SAMPLE-SD-03", None),
    ("Belacan (shrimp paste)", "JAKIM", "SAMPLE-HC-1002", "2027-05-20"),
    ("Sugar", "JAKIM", "SAMPLE-HC-1003", "2027-03-15"),                # expiring after the date jump
    ("Salt", "Supplier declaration", "SAMPLE-SD-04", None),
    ("Tamarind paste", "JAKIM", "SAMPLE-HC-1004", "2027-08-01"),
    ("Vinegar", "JAKIM", "SAMPLE-HC-1005", "2027-06-30"),
    ("Anchovies", "Supplier declaration", "SAMPLE-SD-05", None),
    ("Lemongrass", "Supplier declaration", "SAMPLE-SD-06", None),
]

DOCS = {
    "halal_policy": "## Commitment\nSambal Mak Teh Enterprise (sample) commits to producing food in line with "
                    "MS 1500:2019 and JAKIM's procedures.\n\n## Scope\nSambal Tumis, Sambal Belacan, Sos Cili.\n\n"
                    "## Responsibilities\n- Owner: provides resources and appoints the halal supervisor\n"
                    "- Halal supervisor: checks certificates and records monthly\n- All staff: follow the procedures\n\n"
                    "*Sample draft for owner review.*",
    "ingredient_control": "## Approved suppliers\nBuy only from suppliers on the approved list.\n\n"
                          "## Certificates\nEvery processed ingredient needs a valid certificate from a recognised body. "
                          "Check expiry dates monthly.\n\n## Receiving\nCheck brand and certificate on each delivery.\n\n"
                          "*Sample draft for owner review.*",
    "traceability": "## Batch records\nRecord for every batch: date, ingredients with lot numbers, staff, equipment.\n\n"
                    "## Keeping records\nKeep records for at least two years.\n\n*Sample draft for owner review.*",
}


class Player:
    def __init__(self, backend: str, delay: float):
        self.http = httpx.Client(base_url=backend, timeout=30)
        self.delay = delay

    def call(self, method: str, path: str, **kw):
        resp = self.http.request(method, path, **kw)
        if resp.status_code >= 400:
            sys.exit(f"{method} {path} -> {resp.status_code}: {resp.text}")
        return resp.json()

    def event(self, agent, label, status, handed_to=None):
        time.sleep(self.delay)
        self.call("POST", "/agent/events", json={"business_id": B, "agent": agent, "label": label,
                                                  "status": status, "handed_to": handed_to})
        arrow = f" -> {handed_to}" if handed_to else ""
        print(f"  {agent:<20}{arrow:<24} [{status}] {label}")

    def task(self, frm, to, title, payload=None):
        time.sleep(self.delay)
        t = self.call("POST", "/agent/tasks", json={"business_id": B, "from_agent": frm, "assignee": to,
                                                     "title": title, "payload": payload})
        print(f"  {frm:<20}{' -> ' + to:<24} [task] {title}")
        return t

    def my_tasks(self, agent):
        return self.call("GET", "/agent/tasks", params={"agent": agent, "business_id": B})

    def complete(self, agent, result):
        for t in self.my_tasks(agent):
            self.call("POST", f"/agent/tasks/{t['id']}/complete", json={"agent": agent, "result": result})


def prepare(p: Player):
    p.call("POST", f"/business/{B}/runs", json={"mode": "prepare"})

    print("\nOwner drops the pile")
    uploads = [("files", (name, f"SAMPLE FILE (fictional): {name}\n".encode(), "text/plain"))
               for name, *_ in FILES]
    saved = p.call("POST", f"/business/{B}/files", files=uploads)["files"]
    file_ids = {f["filename"]: f["id"] for f in saved}

    print("\nCoordinator sorts the pile")
    p.event("coordinator", "Sorting 12 files into trays", "action")
    for name, category, kind, zone in FILES:
        p.call("POST", f"/agent/files/{file_ids[name]}/sort",
               json={"category": category, "kind": kind, "zone": zone, "agent": "coordinator"})
    p.event("coordinator", "1 company, 2 product, 4 supplier files", "ok")
    p.event("coordinator", "5 site photos filed by zone", "ok")
    p.task("coordinator", "certificate_checker", "Check supplier invoices and certificates")
    p.task("coordinator", "document_writer", "Start the halal policy and procedures")
    p.task("coordinator", "onsite_inspector", "Check the five zone photos")

    print("\nCertificate Checker")
    p.my_tasks("certificate_checker")
    p.event("certificate_checker", "Reading invoices and recipes", "action")
    p.call("POST", "/agent/ingredients", json={"business_id": B, "ingredients": [
        {"name": n, "brand": b, "kind": k, "proof_type": pt, "supplier_name": s, "product_names": prods}
        for n, b, k, pt, s, prods in INGREDIENTS]})
    p.event("certificate_checker", "12 ingredients from 4 suppliers", "info")
    cert_files = {"Chilli paste": "cert_chilli_paste_SAMPLE.txt", "Belacan (shrimp paste)": "cert_belacan_SAMPLE.txt"}
    for ing, issuer, number, expiry in CERTS:
        res = p.call("POST", "/agent/certificates", json={
            "business_id": B, "ingredient_name": ing, "issuer": issuer, "cert_number": number,
            "expiry_date": expiry, "issuer_recognised": True if issuer == "JAKIM" else None,
            "file_id": file_ids.get(cert_files.get(ing, ""))})
        if res["status"] == "expired":
            p.event("certificate_checker", f"{ing} certificate expired", "problem")
    p.event("certificate_checker", "Cooking oil has no certificate", "problem")
    p.event("certificate_checker", "9 of 11 certificates fine", "ok")
    p.task("certificate_checker", "supplier_chaser", "Chilli paste certificate expired",
           {"ingredient_name": "Chilli paste", "supplier_name": "Rempah Utara Trading (sample)"})
    p.task("certificate_checker", "supplier_chaser", "Cooking oil certificate missing",
           {"ingredient_name": "Cooking oil", "supplier_name": "Pasar Borong Ah Seng (sample)"})
    p.task("certificate_checker", "document_writer", "Confirmed ingredient and supplier list")
    p.task("certificate_checker", "onsite_inspector", "Declared brand list",
           {"brands": [b for _, b, *_ in INGREDIENTS if b]})
    p.complete("certificate_checker", "12 ingredients listed, 2 certificates to chase")

    print("\nSupplier Chaser")
    p.my_tasks("supplier_chaser")
    p.event("supplier_chaser", "Drafting two supplier messages", "action")
    for ing, sup, ms, en in [
        ("Chilli paste", "Rempah Utara Trading (sample)",
         "Assalamualaikum. Sijil halal pes cili (SAMPLE-HC-1001) telah tamat pada 31 Ogos 2026. "
         "Boleh hantar sijil yang baharu? Terima kasih, Mak Teh.",
         "Hello. The halal certificate for the chilli paste (SAMPLE-HC-1001) expired on 31 Aug 2026. "
         "Could you send the renewed one? Thank you, Mak Teh."),
        ("Cooking oil", "Pasar Borong Ah Seng (sample)",
         "Salam. Boleh hantar salinan sijil halal untuk minyak masak Minyak Seri Pagi? Terima kasih, Mak Teh.",
         "Hello. Could you send a copy of the halal certificate for Minyak Seri Pagi cooking oil? "
         "Thank you, Mak Teh."),
    ]:
        p.call("POST", "/agent/approvals", json={"business_id": B, "kind": "message", "agent": "supplier_chaser",
                                                 "supplier_name": sup, "ingredient_name": ing,
                                                 "body_ms": ms, "body_en": en})
        print(f"  supplier_chaser                              [approval] message to {sup}")
    p.event("supplier_chaser", "Two messages wait for owner OK", "attention")

    print("\nDocument Writer")
    p.my_tasks("document_writer")
    for doc_type, body in DOCS.items():
        p.event("document_writer", f"Drafting {doc_type.replace('_', ' ')}", "action")
        p.call("POST", "/agent/documents", json={"business_id": B, "doc_type": doc_type, "body": body})
        p.call("POST", "/agent/approvals", json={"business_id": B, "kind": "document",
                                                 "agent": "document_writer", "doc_type": doc_type})
    p.event("document_writer", "Three drafts ready for review", "ok")
    p.complete("document_writer", "Three drafts sent for approval")

    print("\nOn-site Inspector")
    p.my_tasks("onsite_inspector")
    photo = {zone: file_ids[name] for name, _, _, zone in FILES if zone}
    for zone, severity, title, detail, question in [
        ("processing", "ok", "Surfaces clean, no animals", None, None),
        ("cleaning", "ok", "Cleaning materials kept away from food", None, None),
        ("waste", "ok", "Bins covered", None, None),
        ("packing", "attention", "Pest control sticker has no date",
         "A pest control sticker is on the wall but no service date is visible.",
         "When was the last pest control visit? Please upload the latest report."),
        ("store", "problem", "Undeclared oil brand on shelf",
         "Two bottles of 'Cap Bunga' cooking oil on the second shelf. This brand is not on the declared list.",
         None),
    ]:
        p.call("POST", "/agent/site-findings", json={"business_id": B, "zone": zone, "severity": severity,
                                                     "title": title, "detail": detail, "question": question,
                                                     "photo_file_id": photo[zone]})
        p.event("onsite_inspector", f"{zone.title()}: {title}"[:60], "ok" if severity == "ok" else severity)
    p.task("onsite_inspector", "certificate_checker", "Unknown brand found on site: Cap Bunga oil",
           {"brand": "Cap Bunga", "zone": "store"})
    p.task("onsite_inspector", "document_writer", "Zone details for the procedures")
    p.complete("onsite_inspector", "5 zones checked, 2 possible issues")

    print("\nCertificate Checker (handoff from site)")
    p.my_tasks("certificate_checker")
    p.call("POST", "/agent/ingredients", json={"business_id": B, "ingredients": [{
        "name": "Cooking oil (Cap Bunga)", "brand": "Cap Bunga", "kind": "processed",
        "proof_type": "halal_certificate", "found_on_site": True}]})
    p.event("certificate_checker", "Cap Bunga oil: no certificate", "problem")
    p.complete("certificate_checker", "Added Cap Bunga oil as missing")
    p.complete("document_writer", "Noted zone details")
    p.complete("supplier_chaser", "Messages drafted for approval")

    print("\nCoordinator")
    case = p.call("GET", "/agent/case", params={"business_id": B})
    score = case["readiness"]["score"]
    p.call("POST", "/agent/status", json={"business_id": B, "sentence":
           f"{score}% ready. Two suppliers still owe certificates; I've drafted messages for you to approve."})
    p.event("coordinator", f"Readiness {score}%, waiting on owner", "attention")
    print(f"\nReadiness now {score}% ({case['readiness']['done']}/{case['readiness']['total']}).")


def finish(p: Player):
    print("\nOwner approves everything waiting")
    for a in p.call("GET", f"/business/{B}/approvals", params={"status": "pending"}):
        p.call("POST", f"/approvals/{a['id']}/approve")
        print(f"  owner approved: {a['title']}")
        time.sleep(p.delay)

    print("\nReplies arrive (simulated)")
    p.event("supplier_chaser", "Reply from Rempah Utara with file", "ok")
    p.task("supplier_chaser", "certificate_checker", "Check new certificate from Rempah Utara Trading (sample)")
    p.my_tasks("certificate_checker")
    for ing, number, expiry in [("Chilli paste", "SAMPLE-HC-2001", "2028-08-31"),
                                ("Cooking oil", "SAMPLE-HC-2002", "2028-01-31")]:
        p.call("POST", "/agent/certificates", json={"business_id": B, "ingredient_name": ing, "issuer": "JAKIM",
                                                    "cert_number": number, "expiry_date": expiry,
                                                    "issuer_recognised": True})
        p.event("certificate_checker", f"{ing} certificate now valid", "ok")
    p.complete("certificate_checker", "Two certificates filed")

    print("\nOwner deals with the site findings")
    zones = p.call("GET", f"/business/{B}/site")["zones"]
    for z in zones:
        for f in z["findings"]:
            if f["status"] == "open" and f["severity"] != "ok":
                body = {"status": "resolved"}
                if f["question"]:
                    body["answer"] = "Last visit 2 Oct 2026; report uploaded."
                p.call("PATCH", f"/site-findings/{f['id']}", json=body)
                print(f"  resolved: {f['title']}")
    p.call("POST", "/agent/ingredients", json={"business_id": B, "ingredients": [{
        "name": "Cooking oil (Cap Bunga)", "brand": "Cap Bunga", "kind": "processed",
        "proof_type": "halal_certificate", "found_on_site": True}]})
    p.call("POST", "/agent/certificates", json={"business_id": B, "ingredient_name": "Cooking oil (Cap Bunga)",
                                                "issuer": "JAKIM", "cert_number": "SAMPLE-HC-2003",
                                                "expiry_date": "2027-11-30", "issuer_recognised": True})
    p.event("certificate_checker", "Cap Bunga oil certificate on file", "ok")

    print("\nCoordinator assembles the pack")
    p.event("coordinator", "Assembling the application pack", "action")
    result = p.call("POST", "/agent/pack", params={"business_id": B})
    case = p.call("GET", "/agent/case", params={"business_id": B})
    p.call("POST", "/agent/status", json={"business_id": B, "sentence":
           f"{case['readiness']['score']}% ready. Your pack is ready to download and submit through MYeHALAL."})
    p.event("coordinator", f"Pack ready: {result['items_ready']}/{result['items_total']} items", "ok")


def upkeep(p: Player, days: int):
    p.call("POST", f"/business/{B}/runs", json={"mode": "upkeep"})
    print(f"\nJumping the date forward {days} days")
    clock = p.call("PUT", "/clock", json={"add_days": days, "business_id": B})
    print(f"  today is now {clock['today']}; {len(clock['triggered_tasks'])} renewal task(s) triggered")
    tasks = p.my_tasks("renewal_watch")
    for t in tasks:
        payload = t["payload"] or {}
        p.event("renewal_watch", f"Woke up: {t['title']}"[:60], "attention")
        if payload.get("supplier_name"):
            p.call("POST", "/agent/approvals", json={
                "business_id": B, "kind": "message", "agent": "renewal_watch",
                "supplier_name": payload["supplier_name"], "ingredient_id": payload.get("ingredient_id"),
                "body_ms": f"Salam. Sijil halal kami untuk bekalan anda tamat pada {payload['expiry_date']}. "
                           "Boleh hantar sijil baharu bila sudah diperbaharui? Terima kasih, Mak Teh.",
                "body_en": f"Hello. The halal certificate we hold for your product expires on "
                           f"{payload['expiry_date']}. Could you send the renewed one when ready? Thank you, Mak Teh."})
            p.task("renewal_watch", "supplier_chaser", f"Follow up renewal with {payload['supplier_name']}", payload)
        p.call("POST", f"/agent/tasks/{t['id']}/complete", json={"agent": "renewal_watch",
                                                                 "result": "Renewal request drafted"})
    p.event("renewal_watch", "Back to sleep until next trigger", "info")


def from_run(p: Player, run_id: int, speed: float):
    run = p.call("GET", f"/runs/{run_id}")
    events = [e for e in run["events"] if e["agent"] not in ("owner", "system")]
    p.call("POST", f"/business/{B}/runs", json={"mode": run["run"]["mode"]})
    print(f"\nReplaying {len(events)} agent events from run {run_id} at {speed}x")
    previous = None
    for e in events:
        at = datetime.fromisoformat(e["created_at"])
        if previous and speed > 0:
            time.sleep(min((at - previous).total_seconds() / speed, 3.0))
        previous = at
        p.delay = 0
        p.event(e["agent"], e["label"], e["status"], e["handed_to"])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend", default="http://localhost:8000")
    parser.add_argument("--reset", action="store_true", help="reset the database first")
    parser.add_argument("--finish", action="store_true", help="continue to approvals, replies and the pack")
    parser.add_argument("--upkeep", action="store_true", help="jump the date and wake Renewal Watch")
    parser.add_argument("--days", type=int, default=123, help="days to jump for --upkeep (default 123)")
    parser.add_argument("--from-run", type=int, help="replay the agent events of an earlier run")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--instant", action="store_true")
    args = parser.parse_args()

    delay = 0.0 if args.instant else 1.0 / max(args.speed, 0.01)
    p = Player(args.backend.rstrip("/"), delay)
    print(f"Backend {args.backend}; live stream at {args.backend}/business/{B}/stream")

    if args.reset:
        p.call("POST", "/admin/reset")
        p.call("DELETE", "/clock")
        print("Database reset.")
    if args.from_run:
        from_run(p, args.from_run, 0 if args.instant else args.speed)
        return
    if args.upkeep and not (args.reset or args.finish):
        upkeep(p, args.days)
        return
    prepare(p)
    if args.finish:
        finish(p)
    if args.upkeep:
        upkeep(p, args.days)


if __name__ == "__main__":
    main()
