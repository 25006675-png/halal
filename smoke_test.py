"""
HalalReady — end-to-end smoke test.

Talks to the MCP server over the real streamable-HTTP protocol (not the REST API
directly), so if this passes, WorkBuddy will be able to reach the same tools.

It replays the whole handoff loop with no LLM involved:
    Certificate Checker  -> reads certs, flags problems, creates tasks
    Supplier Chaser      -> picks up tasks, drafts messages, completes them

Run (backend on :8000 and MCP on :8100 must both be up):
    python smoke_test.py
    python smoke_test.py --mcp http://127.0.0.1:8100/mcp

Note: this appends rows every time you run it. Delete backend/halalready.db to
start clean.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date, datetime

from mcp import ClientSession

# mcp 1.x calls this streamablehttp_client and yields (read, write, session_id);
# mcp 2.x calls it streamable_http_client and yields (read, write).
try:
    from mcp.client.streamable_http import streamablehttp_client as _http_client
except ImportError:  # pragma: no cover
    from mcp.client.streamable_http import streamable_http_client as _http_client

MCP_URL = "http://127.0.0.1:8100/mcp"
CASE = "Mak Teh Sambal (sample)"
CHECKER = "Certificate Checker"
CHASER = "Supplier Chaser"

PASS = "  [ok]"
FAIL = "  [FAIL]"

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"{PASS} {label}")
    else:
        print(f"{FAIL} {label}" + (f" — {detail}" if detail else ""))
        failures.append(label)


def payload(result) -> dict:
    """MCP tool results come back as a list of content blocks; ours are JSON text."""
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"raw": text}
    return {}


async def call(session: ClientSession, tool: str, **kwargs) -> dict:
    return payload(await session.call_tool(tool, kwargs))


async def run(mcp_url: str) -> int:
    today = date.today()
    print(f"\nHalalReady smoke test — {today.isoformat()}")
    print(f"MCP: {mcp_url}\n")

    async with _http_client(mcp_url) as streams:
        # Works on both SDK majors: 1.x gives (read, write, session_id), 2.x gives (read, write).
        read, write = streams[0], streams[1]
        async with ClientSession(read, write) as session:
            await session.initialize()

            # -- 0. tools are exposed -------------------------------------- #
            print("1. MCP handshake")
            listing = await session.list_tools()
            names = sorted(t.name for t in listing.tools)
            print(f"   tools: {', '.join(names)}")
            for expected in ("get_certificates", "post_event", "create_task",
                             "get_my_tasks", "complete_task"):
                check(f"tool '{expected}' is exposed", expected in names)

            health = await call(session, "backend_health")
            check("backend reachable through MCP", health.get("ok") is True,
                  str(health.get("error", "")))

            # -- 1. certificate checker ------------------------------------ #
            print("\n2. Certificate Checker reads the sample case")
            certs = await call(session, "get_certificates", case_name=CASE)
            check("get_certificates returns ok", certs.get("ok") is True)
            rows = certs.get("certificates", [])
            check("3 certificates seeded", len(rows) == 3, f"got {len(rows)}")
            if len(rows) != 3:
                return 1

            await call(session, "post_event", agent=CHECKER,
                       step=f"Starting certificate check for {CASE} as at {today.isoformat()}")

            flagged = []
            for cert in rows:
                valid_until = cert.get("valid_until")
                if not valid_until:
                    issue, detail = "missing", "No certificate on file."
                else:
                    expiry = datetime.strptime(valid_until, "%Y-%m-%d").date()
                    if expiry < today:
                        issue = "expired"
                        detail = f"Certificate expired {(today - expiry).days} days ago on {valid_until}."
                    else:
                        issue = "valid"
                        detail = f"Certificate valid until {valid_until}."

                await call(session, "post_event", agent=CHECKER,
                           step=f"{cert['item']} — {cert['supplier']}: {detail}")

                if issue in ("expired", "missing"):
                    task = await call(
                        session, "create_task",
                        to_agent=CHASER, from_agent=CHECKER,
                        what=f"Request a valid halal certificate from {cert['supplier']} for {cert['item']}",
                        data={"case_name": CASE, "supplier": cert["supplier"],
                              "item": cert["item"], "cert_no": cert.get("cert_no", ""),
                              "valid_until": valid_until, "issue": issue, "detail": detail},
                    )
                    check(f"task created for {cert['supplier']} ({issue})",
                          task.get("ok") is True and task["task"]["status"] == "open")
                    flagged.append((cert, issue, task["task"]["id"]))

            check("2 problems flagged (1 expired, 1 missing)", len(flagged) == 2,
                  f"got {len(flagged)}")

            # create_task must have logged the handoff event itself
            events = await call(session, "get_timeline", limit=100)
            handoffs = [e for e in events.get("events", []) if e.get("handed_to") == CHASER]
            check("create_task also logged the handoff events", len(handoffs) >= 2,
                  f"found {len(handoffs)} handoff events")

            await call(session, "post_event", agent=CHECKER,
                       step="Check complete: 1 expired, 1 missing, 1 valid. "
                            "2 tasks handed to Supplier Chaser. No halal determination made.")

            # -- 2. supplier chaser ---------------------------------------- #
            print("\n3. Supplier Chaser picks up the work")
            mine = await call(session, "get_my_tasks", agent=CHASER)
            check("get_my_tasks returns ok", mine.get("ok") is True)
            open_tasks = mine.get("tasks", [])
            check("chaser sees the handed-off tasks", len(open_tasks) >= 2,
                  f"got {len(open_tasks)}")

            drafted = 0
            for task in open_tasks[:2]:
                d = task.get("data", {})
                supplier, item, issue = d.get("supplier", "?"), d.get("item", "?"), d.get("issue")

                await call(session, "post_event", agent=CHASER,
                           step=f"Drafting certificate request for {supplier} ({item}, certificate {issue})")

                if issue == "expired":
                    body = (f"Salam, ini pasukan dokumentasi halal kami. Kami sedang lengkapkan fail "
                            f"pensijilan halal dan sijil untuk {item} daripada pihak anda sudah tamat "
                            f"tempoh pada {d.get('valid_until')}. Bolehkah pihak anda hantar salinan "
                            f"sijil terkini dalam minggu ini? Terima kasih.")
                else:
                    body = (f"Salam, ini pasukan dokumentasi halal kami. Kami sedang lengkapkan fail "
                            f"pensijilan halal dan belum ada sijil halal untuk {item} daripada pihak "
                            f"anda. Bolehkah pihak anda hantar salinan sijil terkini dalam minggu ini? "
                            f"Terima kasih.")

                draft = (f"DRAFT — WhatsApp to {supplier} ({item})\n\n{body}\n\n[Not sent — draft only]")

                done = await call(session, "complete_task", task_id=task["id"], result=draft)
                check(f"task {task['id']} completed with a draft",
                      done.get("ok") is True and done["task"]["status"] == "done")
                check(f"draft for {supplier} is marked not-sent",
                      "[Not sent — draft only]" in done["task"]["result"])
                drafted += 1

                await call(session, "post_event", agent=CHASER,
                           step=f"Draft ready for {supplier} — awaiting human review before sending")

            check("a draft was produced for every flagged supplier", drafted == len(flagged),
                  f"{drafted} of {len(flagged)}")

            await call(session, "post_event", agent=CHASER,
                       step=f"All supplier drafts ready: {drafted} of {drafted}. "
                            "Nothing sent — awaiting human review.")

            # -- 3. final state -------------------------------------------- #
            print("\n4. Final state")
            final = await call(session, "backend_health")
            counts = final.get("counts", {})
            print(f"   rows: {counts}")
            check("events were logged", counts.get("events", 0) >= 6,
                  f"got {counts.get('events')}")
            check("tasks exist", counts.get("tasks", 0) >= 2, f"got {counts.get('tasks')}")

            still_open = (await call(session, "get_my_tasks", agent=CHASER)).get("tasks", [])
            check("no open tasks left for the chaser", len(still_open) == 0,
                  f"{len(still_open)} still open")

    print("\n" + "=" * 58)
    if failures:
        print(f"RESULT: {len(failures)} check(s) failed")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("RESULT: all checks passed — the two agents handed work to each other.")
    print("Open http://127.0.0.1:8000/events/view to watch the timeline.")
    print("=" * 58)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="HalalReady end-to-end smoke test")
    parser.add_argument("--mcp", default=MCP_URL)
    args = parser.parse_args()
    try:
        sys.exit(asyncio.run(run(args.mcp)))
    except Exception as exc:  # noqa: BLE001
        print(f"\nCould not complete the test: {type(exc).__name__}: {exc}")
        print("Is the MCP server running on :8100 and the backend on :8000?")
        sys.exit(2)


if __name__ == "__main__":
    main()
