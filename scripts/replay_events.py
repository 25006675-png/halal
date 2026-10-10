"""
HalalReady — Fake Event Replay Script
Proposal §9 (Person 2): "Build post_event and the live stream first,
plus a fake event replay script for Person 1."

This script creates a run, then replays a realistic sequence of events
that simulate the full Mak Teh demo flow:
  1. Coordinator sorts files
  2. Certificate Checker inspects each ingredient
  3. Handoff to Supplier Chaser for expired/missing certs
  4. Document Writer drafts documents
  5. On-site Inspector checks zones
  6. Coordinator assembles the pack

Events are posted with realistic delays (configurable speed multiplier).
Person 1 can watch them arrive on GET /runs/{id}/stream.

Usage:
  python scripts/replay_events.py           # normal speed (1s between events)
  python scripts/replay_events.py --fast    # 0.2s between events
  python scripts/replay_events.py --instant # no delay
"""

import httpx, time, argparse, sys

BACKEND = "http://localhost:8000"
BUSINESS_ID = 1


def post(path, body):
    resp = httpx.post(f"{BACKEND}{path}", json=body, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    print(f"  → {path}: {data}")
    return data


def wait(delay):
    if delay > 0:
        time.sleep(delay)


# ── the demo script ─────────────────────────────────────────────────

SCRIPT = [
    # Phase 1: Coordinator sorts the pile
    {"agent": "coordinator",         "label": "Received 8 files from owner",             "status": "info"},
    {"agent": "coordinator",         "label": "Sorting files into input trays",          "status": "action"},
    {"agent": "coordinator",         "label": "3 invoices filed",                        "status": "ok"},
    {"agent": "coordinator",         "label": "4 certificates filed",                    "status": "ok"},
    {"agent": "coordinator",         "label": "1 site photo filed",                      "status": "ok"},
    {"agent": "coordinator",         "label": "Starting certificate check",              "status": "action",    "handed_to": "certificate_checker"},

    # Phase 2: Certificate Checker
    {"agent": "certificate_checker", "label": "Reading case: 12 ingredients found",      "status": "info"},
    {"agent": "certificate_checker", "label": "Dried chilli cert valid until Jun 2027",  "status": "ok"},
    {"agent": "certificate_checker", "label": "Fresh red chilli is natural, covered",    "status": "ok"},
    {"agent": "certificate_checker", "label": "Shallots are natural, covered",           "status": "ok"},
    {"agent": "certificate_checker", "label": "Garlic is natural, covered",              "status": "ok"},
    {"agent": "certificate_checker", "label": "Belacan certificate expired Aug 2026",    "status": "problem",   "_finding": {"category": "certificate", "severity": "problem", "title": "Belacan certificate expired", "detail": "JAKIM/HC-2024/5678 expired 2026-08-10. Supplier: Belacan Melaka Asli.", "ingredient_id": 5}},
    {"agent": "certificate_checker", "label": "Palm oil cert valid until Sep 2027",      "status": "ok"},
    {"agent": "certificate_checker", "label": "Sugar cert valid until Mar 2027",         "status": "ok"},
    {"agent": "certificate_checker", "label": "Salt is natural, covered",                "status": "ok"},
    {"agent": "certificate_checker", "label": "Tamarind paste cert valid (MUI)",         "status": "ok"},
    {"agent": "certificate_checker", "label": "Vinegar cert valid (IFANCA)",             "status": "ok"},
    {"agent": "certificate_checker", "label": "Modified starch cert valid",              "status": "ok"},
    {"agent": "certificate_checker", "label": "Unknown cooking oil has NO certificate",  "status": "problem",   "_finding": {"category": "certificate", "severity": "problem", "title": "Unknown cooking oil missing certificate", "detail": "Ingredient 12 has no supplier or certificate on file.", "ingredient_id": 12}},
    {"agent": "certificate_checker", "label": "2 problems found, handing to chaser",    "status": "attention", "handed_to": "supplier_chaser"},
    {"agent": "certificate_checker", "label": "Ingredient list ready for doc writer",    "status": "ok",        "handed_to": "document_writer"},
    {"agent": "certificate_checker", "label": "Brand list sent to site inspector",       "status": "ok",        "handed_to": "onsite_inspector"},

    # Phase 3: Supplier Chaser
    {"agent": "supplier_chaser",     "label": "Drafting message for Belacan Melaka",     "status": "action",    "_task": {"type": "supplier_message", "supplier_id": 4, "channel": "whatsapp", "body_ms": "Assalamualaikum Encik Roslan,\n\nSijil halal JAKIM/HC-2024/5678 untuk Belacan Melaka telah tamat tempoh pada 10 Ogos 2026.\n\nSila hantar sijil halal yang diperbaharui secepat mungkin.\n\nTerima kasih.", "body_en": "Dear Mr Roslan,\n\nThe halal certificate JAKIM/HC-2024/5678 for Belacan Melaka expired on 10 Aug 2026.\n\nPlease send the renewed certificate at your earliest convenience.\n\nThank you.", "assignee": "supplier_chaser"}},
    {"agent": "supplier_chaser",     "label": "Draft message ready, needs owner OK",    "status": "action"},
    {"agent": "supplier_chaser",     "label": "Unknown oil needs supplier identified",  "status": "attention", "_task": {"type": "supplier_message", "channel": "manual", "body_ms": "Sila kenal pasti pembekal untuk minyak masak yang tidak dikenali dan dapatkan sijil halal.", "body_en": "Please identify the supplier for the unknown cooking oil and obtain a halal certificate.", "assignee": "supplier_chaser"}},

    # Phase 4: Document Writer (runs in parallel with chaser)
    {"agent": "document_writer",     "label": "Starting halal policy draft",             "status": "action",    "_doc": {"title": "Halal Policy", "body": "# Halal Policy — Mak Teh's Sambal Dapur Sdn Bhd\n\n## Commitment\nMak Teh's Sambal Dapur is committed to producing halal food products in accordance with MS 1500:2019 and MPPHM guidelines.\n\n## Scope\nThis policy covers all products: Sambal Tumis, Sambal Belacan Original, and Sos Cili.\n\n## Responsibilities\n- Management: ensure resources for halal compliance\n- Halal Committee: monitor and enforce halal procedures\n- All staff: follow halal procedures in daily operations"}},
    {"agent": "document_writer",     "label": "Halal policy draft complete",             "status": "ok"},
    {"agent": "document_writer",     "label": "Starting ingredient control procedure",   "status": "action",    "_doc": {"title": "Ingredient Control", "body": "# Ingredient Control Procedure\n\n## 1. Approved Supplier List\nAll ingredients must come from suppliers on the approved list.\n\n## 2. Certificate Verification\nEvery processed ingredient requires a valid halal certificate from a JAKIM-recognised body.\n\n## 3. Receiving Inspection\nCheck each delivery against the approved list and certificate records.\n\n## 4. Segregation\nStore halal and non-certified ingredients separately."}},
    {"agent": "document_writer",     "label": "Ingredient control procedure done",       "status": "ok"},
    {"agent": "document_writer",     "label": "Starting traceability procedure",         "status": "action",    "_doc": {"title": "Traceability Procedure", "body": "# Traceability Procedure\n\n## Batch Tracking\nEvery production batch is recorded with:\n- Date and time\n- Ingredients used (with batch/lot numbers)\n- Staff on duty\n- Equipment used\n\n## Record Keeping\nAll records kept for minimum 2 years."}},
    {"agent": "document_writer",     "label": "Traceability procedure done",             "status": "ok"},
    {"agent": "document_writer",     "label": "3 documents drafted, need owner review",  "status": "action"},

    # Phase 5: On-site Inspector
    {"agent": "onsite_inspector",    "label": "Starting site check: 4 areas",            "status": "action"},
    {"agent": "onsite_inspector",    "label": "Receiving area: clean, no issues",        "status": "ok",        "_site": {"area": "receiving", "severity": "info", "title": "Receiving area clear", "detail": "Clean loading bay. Incoming inspection checklist present."}},
    {"agent": "onsite_inspector",    "label": "Dry store: undeclared oil brand found",   "status": "problem",   "_site": {"area": "dry_store", "severity": "problem", "title": "Undeclared cooking oil brand on shelf", "detail": "A bottle of 'Cap Bunga' cooking oil found on shelf B3. This brand is not on the declared ingredient list.", "handed_to": "certificate_checker"}},
    {"agent": "onsite_inspector",    "label": "Unknown brand handed to cert checker",    "status": "attention", "handed_to": "certificate_checker"},
    {"agent": "onsite_inspector",    "label": "Production area: mostly clear",           "status": "ok",        "_site": {"area": "production", "severity": "info", "title": "Production area generally compliant", "detail": "Clean work surfaces. Halal signage visible. Staff wearing proper attire."}},
    {"agent": "onsite_inspector",    "label": "Packing: pest control sign needs date",   "status": "attention", "_site": {"area": "packing", "severity": "attention", "title": "Pest control record not dated", "detail": "Pest control service sticker on wall but no date of last service visible. Ask owner for pest control records."}},
    {"agent": "onsite_inspector",    "label": "Site check complete: 1 problem, 1 note",  "status": "info"},

    # Phase 6: Coordinator wraps up
    {"agent": "coordinator",         "label": "All agents reported, updating score",     "status": "action"},
    {"agent": "coordinator",         "label": "Readiness: 69%. Two items blocking.",     "status": "attention"},
    {"agent": "coordinator",         "label": "Waiting for owner actions on 2 tasks",    "status": "info"},
]


def main():
    parser = argparse.ArgumentParser(description="Replay fake events for dashboard development")
    parser.add_argument("--fast", action="store_true", help="0.2s between events")
    parser.add_argument("--instant", action="store_true", help="No delay")
    parser.add_argument("--sim-date", default=None, help="Override date (YYYY-MM-DD)")
    args = parser.parse_args()

    delay = 1.0
    if args.fast:
        delay = 0.2
    if args.instant:
        delay = 0.0

    print(f"\n🟢 Starting fake event replay (delay={delay}s)")
    print(f"   Backend: {BACKEND}")
    print(f"   Business: {BUSINESS_ID}\n")

    # Create a run
    run = post(f"/business/{BUSINESS_ID}/runs", {"sim_date": args.sim_date})
    run_id = run["id"]
    print(f"\n📋 Run #{run_id} created. Stream at: {BACKEND}/runs/{run_id}/stream\n")
    print("=" * 60)

    for i, step in enumerate(SCRIPT, 1):
        wait(delay)
        print(f"\n[{i}/{len(SCRIPT)}] {step['agent']}: {step['label']}")

        finding_id = None

        # Create finding if needed
        if "_finding" in step:
            f = step["_finding"]
            result = post("/findings", {
                "run_id": run_id,
                "agent": step["agent"],
                **f,
            })
            finding_id = result["id"]

        # Create site finding if needed
        if "_site" in step:
            sf = step["_site"]
            post("/site-findings", {
                "business_id": BUSINESS_ID,
                "run_id": run_id,
                **{k: v for k, v in sf.items() if k != "handed_to"},
            })

        # Create task if needed
        if "_task" in step:
            t = step["_task"]
            if finding_id:
                t["finding_id"] = finding_id
            post("/tasks", t)

        # Create document if needed
        if "_doc" in step:
            d = step["_doc"]
            post("/documents", {"business_id": BUSINESS_ID, **d})

        # Post the event
        event_data = {
            "run_id": run_id,
            "agent": step["agent"],
            "label": step["label"],
            "status": step["status"],
        }
        if finding_id:
            event_data["finding_id"] = finding_id
        if step.get("handed_to"):
            event_data["handed_to"] = step["handed_to"]
        post("/events", event_data)

    print("\n" + "=" * 60)
    print(f"\n✅ Replay complete! {len(SCRIPT)} events posted to run #{run_id}")
    print(f"   Dashboard stream: {BACKEND}/runs/{run_id}/stream")
    print(f"   Overview:         {BACKEND}/business/{BUSINESS_ID}/overview")
    print(f"   Ingredients:      {BACKEND}/business/{BUSINESS_ID}/ingredients")
    print(f"   Site check:       {BACKEND}/business/{BUSINESS_ID}/site-check")
    print(f"   Pack:             {BACKEND}/business/{BUSINESS_ID}/pack\n")


if __name__ == "__main__":
    main()
