"""
HalalReady — MCP server (FastMCP, streamable HTTP on port 8100).

This is the only thing the two WorkBuddy agents talk to. It is a thin wrapper
around the backend REST API, so the backend stays the single source of truth
and you can watch everything happen in the browser at:

    http://127.0.0.1:8000/events/view

Run (backend must already be up):
    python server.py
    # or: python server.py --port 8100 --backend http://127.0.0.1:8000

Endpoint to register in WorkBuddy Connectors:
    http://127.0.0.1:8100/mcp
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

import httpx

# The MCP Python SDK renamed FastMCP to MCPServer in v2 and moved host/port from
# the constructor onto run(). Support both, so this file works whether
# `pip install mcp` gives you 1.x (FastMCP) or 2.x (MCPServer).
try:  # mcp 1.x — the classic FastMCP API
    from mcp.server.fastmcp import FastMCP as _MCPServer

    _SDK_LABEL = "mcp 1.x (FastMCP)"
    _SDK_V2 = False
except ModuleNotFoundError:  # mcp 2.x — same decorators, renamed class
    from mcp.server.mcpserver import MCPServer as _MCPServer

    _SDK_LABEL = "mcp 2.x (MCPServer)"
    _SDK_V2 = True

BACKEND = os.environ.get("HALALREADY_BACKEND", "http://127.0.0.1:8000")
MCP_HOST = os.environ.get("HALALREADY_MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.environ.get("HALALREADY_MCP_PORT", "8100"))
MCP_PATH = "/mcp"

INSTRUCTIONS = (
    "Shared blackboard for the HalalReady halal-certification paperwork agents. "
    "Use get_certificates() to read the sample case, post_event() to log every step, "
    "create_task() to hand work to another agent (this also logs the handoff), "
    "get_my_tasks() to pick up work, and complete_task() to return a result. "
    "This server records paperwork only. It never determines halal status."
)

# mcp 2.x takes host/port in run(); mcp 1.x takes them here.
mcp = _MCPServer(
    "HalalReady",
    instructions=INSTRUCTIONS,
    **({} if _SDK_V2 else {"host": MCP_HOST, "port": MCP_PORT}),
)


# --------------------------------------------------------------------------- #
# Backend helpers
# --------------------------------------------------------------------------- #

def _client() -> httpx.Client:
    return httpx.Client(base_url=BACKEND, timeout=15.0)


def _fail(exc: Exception) -> dict[str, Any]:
    return {
        "ok": False,
        "error": f"{type(exc).__name__}: {exc}",
        "hint": f"Is the backend running at {BACKEND}? Try: curl {BACKEND}/health",
    }


def _request(method: str, path: str, **kwargs: Any) -> Any:
    with _client() as client:
        response = client.request(method, path, **kwargs)
        response.raise_for_status()
        if not response.content:
            return None
        return response.json()


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #

@mcp.tool()
def get_certificates(case_name: str = "") -> dict[str, Any]:
    """List the supplier certificates in the sample case.

    Each item has: supplier, item, cert_no, valid_until (ISO date, or null when
    the supplier has supplied no certificate) and notes.

    Args:
        case_name: Optional. Leave empty to get every case. The sample case is
            "Mak Teh Sambal (sample)".
    """
    try:
        params = {"case_name": case_name} if case_name else {}
        certs = _request("GET", "/certificates", params=params)
        return {"ok": True, "count": len(certs), "certificates": certs}
    except Exception as exc:  # noqa: BLE001 - surfaced to the agent as text
        return _fail(exc)


@mcp.tool()
def post_event(agent: str, step: str, handed_to: str = "") -> dict[str, Any]:
    """Log one step to the shared handoff timeline.

    Call this for every meaningful step, even when you are not handing anything
    off. The human watches this timeline, so write it as a plain sentence.

    Args:
        agent: Your own agent name, e.g. "Certificate Checker".
        step: What you just did, e.g. "Checked 3 certificates against 2026-10-10".
        handed_to: Agent you handed work to, or "" if you kept the work.
    """
    try:
        event = _request(
            "POST",
            "/events",
            json={"agent": agent, "step": step, "handed_to": handed_to},
        )
        return {"ok": True, "event": event}
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


@mcp.tool()
def create_task(
    to_agent: str,
    from_agent: str,
    what: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Hand work to another agent. This also logs the handoff event for you.

    Args:
        to_agent: Who should do the work, e.g. "Supplier Chaser".
        from_agent: Who is handing it over, e.g. "Certificate Checker".
        what: One-line description of the work.
        data: Structured payload the other agent needs — e.g.
            {"case_name": "...", "supplier": "...", "item": "...",
             "cert_no": "...", "valid_until": "...", "issue": "expired"}.
    """
    try:
        task = _request(
            "POST",
            "/tasks",
            json={
                "to_agent": to_agent,
                "from_agent": from_agent,
                "what": what,
                "data": data or {},
            },
        )
        return {"ok": True, "task": task, "note": "Handoff event logged automatically."}
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


@mcp.tool()
def get_my_tasks(agent: str) -> dict[str, Any]:
    """Get the open tasks waiting for this agent.

    Args:
        agent: Your own agent name, e.g. "Supplier Chaser". Must match the
            to_agent used when the task was created.
    """
    try:
        tasks = _request("GET", "/tasks", params={"agent": agent, "status": "open"})
        return {"ok": True, "count": len(tasks), "tasks": tasks}
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


@mcp.tool()
def complete_task(task_id: int, result: str) -> dict[str, Any]:
    """Mark a task done and hand back the result.

    Args:
        task_id: The id from get_my_tasks().
        result: What you produced. For the Supplier Chaser this is the draft
            message text. Nothing is ever sent to a supplier.
    """
    try:
        task = _request("POST", f"/tasks/{task_id}/complete", json={"result": result})
        return {"ok": True, "task": task}
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


@mcp.tool()
def get_timeline(limit: int = 50) -> dict[str, Any]:
    """Read back the shared handoff timeline (newest first). Handy for checking
    what the other agent has already done.

    Args:
        limit: How many events to return.
    """
    try:
        events = _request("GET", "/events", params={"limit": limit})
        return {"ok": True, "count": len(events), "events": events}
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


@mcp.tool()
def backend_health() -> dict[str, Any]:
    """Check the backend is reachable and see row counts. Use this first if
    something looks wrong."""
    try:
        return {"ok": True, **_request("GET", "/health")}
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def main() -> None:
    global BACKEND
    parser = argparse.ArgumentParser(description="HalalReady MCP server")
    parser.add_argument("--host", default=MCP_HOST)
    parser.add_argument("--port", type=int, default=MCP_PORT)
    parser.add_argument("--backend", default=BACKEND)
    args = parser.parse_args()

    BACKEND = args.backend

    print("HalalReady MCP server")
    print(f"  sdk      -> {_SDK_LABEL}")
    print(f"  backend  -> {BACKEND}")
    print(f"  MCP URL  -> http://{args.host}:{args.port}{MCP_PATH}")
    print(f"  live log -> {BACKEND}/events/view")

    if _SDK_V2:
        mcp.run(transport="streamable-http", host=args.host, port=args.port,
                streamable_http_path=MCP_PATH)
    else:
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.settings.streamable_http_path = MCP_PATH
        mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
