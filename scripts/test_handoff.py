"""
HalalReady: two-agent handoff test through the real MCP connector.

First milestone (proposal §9): the Certificate Checker hands a task to the
Supplier Chaser through the connector, visible on the events stream.

This starts connector/server.py over stdio exactly as WorkBuddy would, and
plays both agents through its tools. The owner's approval goes through the
dashboard endpoint.

    python -m uvicorn backend.app:app --port 8000     # in one terminal
    python scripts/test_handoff.py                     # in another
    python scripts/test_handoff.py --backend http://localhost:8011
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent


async def run(backend: str) -> int:
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "connector" / "server.py")],
        env={**os.environ, "BACKEND_URL": backend},
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = sorted(t.name for t in (await session.list_tools()).tools)
        print(f"Connector tools ({len(tools)}): {', '.join(tools)}\n")

        async def tool(name: str, **args):
            result = await session.call_tool(name, args)
            text = result.content[0].text if result.content else ""
            if result.isError:
                raise RuntimeError(f"{name} failed: {text}")
            data = result.structuredContent
            if isinstance(data, dict) and set(data) == {"result"}:
                data = data["result"]
            if data is None:
                data = json.loads(text)
            return data

        start = httpx.get(f"{backend}/business/1/events", params={"limit": 1000}).json()
        after_id = start[-1]["id"] if start else 0

        print("Certificate Checker")
        await tool("save_ingredients", ingredients=[{
            "name": "Belacan (shrimp paste)", "brand": "Belacan Melaka", "kind": "processed",
            "proof_type": "halal_certificate", "supplier_name": "Belacan Melaka Asli (sample)",
            "product_names": ["Sambal Belacan"]}])
        cert = await tool("save_certificate", ingredient_name="Belacan (shrimp paste)", issuer="JAKIM",
                          cert_number="SAMPLE-JAKIM-5678", expiry_date="2026-08-10", issuer_recognised=True)
        print(f"  belacan certificate status: {cert['status']} ({cert['days_to_expiry']} days)")
        await tool("post_event", agent="certificate_checker", label="Belacan certificate expired", status="problem")
        task = await tool("create_task", from_agent="certificate_checker", assignee="supplier_chaser",
                          title="Ask Belacan Melaka for a renewed certificate",
                          payload={"ingredient_id": cert["ingredient_id"], "status": cert["status"]})
        print(f"  handed task #{task['id']} to supplier_chaser\n")

        print("Supplier Chaser")
        mine = await tool("get_my_tasks", agent="supplier_chaser")
        picked = next(t for t in mine if t["id"] == task["id"])
        print(f"  picked up task #{picked['id']}: {picked['title']} ({picked['status']})")
        approval = await tool("request_approval", kind="message", agent="supplier_chaser",
                              supplier_name="Belacan Melaka Asli (sample)",
                              ingredient_id=cert["ingredient_id"],
                              body_ms="Salam Encik Roslan, sijil halal belacan telah tamat. Boleh hantar sijil baharu?",
                              body_en="Hello Mr Roslan, the belacan halal certificate has expired. "
                                      "Could you send the renewed one?")
        print(f"  approval #{approval['id']} waiting for the owner")

        sent = httpx.post(f"{backend}/approvals/{approval['id']}/approve").json()
        print(f"  owner approved -> {sent['status']} via {sent['channel']}")
        await tool("complete_task", task_id=task["id"], agent="supplier_chaser", result="Message sent to supplier")

    events = httpx.get(f"{backend}/business/1/events", params={"after_id": after_id}).json()
    print("\nEvents posted during the test:")
    for e in events:
        arrow = f" -> {e['handed_to']}" if e["handed_to"] else ""
        print(f"  #{e['id']:<4} {e['agent']:<20}{arrow:<24} [{e['status']}] {e['label']}")

    handoff = [e for e in events if e["agent"] == "certificate_checker" and e["handed_to"] == "supplier_chaser"]
    done = [e for e in events if e["agent"] == "supplier_chaser" and e["task_id"] == task["id"] and e["status"] == "ok"]
    ok = bool(handoff) and bool(done) and cert["status"] == "expired"
    print("\nPASS: handoff visible in events" if ok else "\nFAIL: handoff not found in events")
    return 0 if ok else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend", default=os.getenv("BACKEND_URL", "http://localhost:8000"))
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args.backend.rstrip("/"))))


if __name__ == "__main__":
    main()
