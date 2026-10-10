"""
HalalReady — Two-Agent Handoff Test
Proposal §10: "First milestone: two agents (Certificate Checker → Supplier Chaser)
hand off a task through the connector, visible on the events page."

This script simulates:
  1. Certificate Checker finds an expired cert
  2. Creates a finding
  3. Creates a task assigned to Supplier Chaser
  4. Posts an event with handed_to = supplier_chaser
  5. Supplier Chaser picks up the task
  6. Drafts a message
  7. Completes the task

Run the backend first: python backend/app.py
Then run this:    python scripts/test_handoff.py
"""

import httpx, json, time

BACKEND = "http://localhost:8000"
BUSINESS_ID = 1


def api(method, path, body=None):
    url = f"{BACKEND}{path}"
    if method == "GET":
        r = httpx.get(url, timeout=10)
    elif method == "POST":
        r = httpx.post(url, json=body, timeout=10)
    elif method == "PATCH":
        r = httpx.patch(url, json=body, timeout=10)
    else:
        raise ValueError(method)
    r.raise_for_status()
    data = r.json()
    print(f"  {method} {path} → {json.dumps(data, indent=2)[:200]}")
    return data


def main():
    print("\n" + "=" * 60)
    print("🧪 Two-Agent Handoff Test")
    print("   Certificate Checker → Supplier Chaser")
    print("=" * 60)

    # Step 1: Start a run
    print("\n📋 Step 1: Start a run")
    run = api("POST", f"/business/{BUSINESS_ID}/runs", {})
    run_id = run["id"]

    # Step 2: Certificate Checker finds expired belacan cert
    print("\n🔍 Step 2: Certificate Checker finds expired certificate")
    api("POST", "/events", {
        "run_id": run_id,
        "agent": "certificate_checker",
        "label": "Checking belacan certificate",
        "status": "action",
    })
    time.sleep(0.3)

    # Step 3: Create a finding
    print("\n⚠️  Step 3: Create finding for expired cert")
    finding = api("POST", "/findings", {
        "run_id": run_id,
        "agent": "certificate_checker",
        "category": "certificate",
        "severity": "problem",
        "title": "Belacan halal cert expired",
        "detail": "JAKIM/HC-2024/5678 expired 10 Aug 2026",
        "ingredient_id": 5,
    })
    finding_id = finding["id"]

    api("POST", "/events", {
        "run_id": run_id,
        "agent": "certificate_checker",
        "label": "Belacan certificate expired Aug 2026",
        "status": "problem",
        "finding_id": finding_id,
    })
    time.sleep(0.3)

    # Step 4: Create a task and hand off
    print("\n📤 Step 4: Create task & hand off to supplier_chaser")
    task = api("POST", "/tasks", {
        "finding_id": finding_id,
        "type": "supplier_message",
        "supplier_id": 4,
        "channel": "whatsapp",
        "body_ms": "Sijil halal belacan telah tamat. Sila hantar sijil baharu.",
        "body_en": "Belacan halal cert expired. Please send renewed cert.",
        "assignee": "supplier_chaser",
    })
    task_id = task["id"]

    api("POST", "/events", {
        "run_id": run_id,
        "agent": "certificate_checker",
        "label": "Handed expired cert to supplier chaser",
        "status": "action",
        "finding_id": finding_id,
        "handed_to": "supplier_chaser",
    })
    time.sleep(0.5)

    # Step 5: Supplier Chaser picks up the task
    print("\n📥 Step 5: Supplier Chaser picks up task")
    tasks = api("GET", "/tasks/agent/supplier_chaser")
    print(f"     Found {len(tasks)} task(s) assigned")

    api("POST", "/events", {
        "run_id": run_id,
        "agent": "supplier_chaser",
        "label": "Picked up expired belacan cert task",
        "status": "action",
    })
    time.sleep(0.3)

    # Step 6: Supplier Chaser drafts message, requests approval
    print("\n✉️  Step 6: Draft message ready, requesting approval")
    api("POST", "/events", {
        "run_id": run_id,
        "agent": "supplier_chaser",
        "label": "Draft WhatsApp message ready for owner",
        "status": "action",
    })
    api("POST", "/approvals/request", {
        "item_type": "task",
        "item_id": task_id,
    })
    time.sleep(0.3)

    # Step 7: Owner approves (simulated)
    print("\n✅ Step 7: Owner approves the message")
    api("PATCH", f"/tasks/{task_id}", {"status": "approved"})
    time.sleep(0.3)

    # Step 8: Supplier Chaser marks task done
    print("\n🏁 Step 8: Supplier Chaser completes the task")
    api("POST", f"/tasks/{task_id}/complete")

    api("POST", "/events", {
        "run_id": run_id,
        "agent": "supplier_chaser",
        "label": "Belacan supplier message sent",
        "status": "ok",
    })

    # Summary
    print("\n" + "=" * 60)
    print("✅ Handoff test complete!")
    print(f"   Run ID:     {run_id}")
    print(f"   Finding ID: {finding_id}")
    print(f"   Task ID:    {task_id}")
    print(f"\n   View run:   {BACKEND}/runs/{run_id}")
    print(f"   Stream:     {BACKEND}/runs/{run_id}/stream")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
