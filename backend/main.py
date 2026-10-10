"""
HalalReady — backend API (FastAPI + SQLite).

Purpose: a shared, dumb "blackboard" that two agents use to hand work to each
other. One agent writes events and creates tasks; the other agent reads its
tasks, posts events, and completes them. Nothing here makes any halal
determination — it just records what the agents did.

Run:
    python -m uvicorn main:app --host 127.0.0.1 --port 8000

Watch handoffs live in a browser:
    http://127.0.0.1:8000/events/view
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("HALALREADY_DB", os.path.join(BASE_DIR, "halalready.db"))

SAMPLE_CASE = "Mak Teh Sambal (sample)"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    time      TEXT NOT NULL,
    agent     TEXT NOT NULL,
    step      TEXT NOT NULL,
    handed_to TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS tasks (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    to_agent  TEXT NOT NULL,
    from_agent TEXT NOT NULL,
    what      TEXT NOT NULL,
    data      TEXT NOT NULL DEFAULT '{}',
    status    TEXT NOT NULL DEFAULT 'open',
    result    TEXT NOT NULL DEFAULT ''
);

-- Not in the original table list, but the certificate-checker agent needs
-- something to check. Kept deliberately simple: one row per supplier cert.
CREATE TABLE IF NOT EXISTS certificates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    case_name   TEXT NOT NULL,
    supplier    TEXT NOT NULL,
    item        TEXT NOT NULL,
    cert_no     TEXT NOT NULL DEFAULT '',
    valid_until TEXT,                 -- ISO date 'YYYY-MM-DD', NULL = no certificate
    notes       TEXT NOT NULL DEFAULT ''
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        seed(conn)
    finally:
        conn.close()


def seed(conn: sqlite3.Connection) -> None:
    """Insert the one fictional sample case. Idempotent."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM certificates WHERE case_name = ?", (SAMPLE_CASE,)
    ).fetchone()
    if row["n"]:
        return

    rows = [
        # item, supplier, cert_no, valid_until, notes
        ("Chilli paste", "Syarikat Cili Maju", "HAL-2024-8871", "2026-08-14",
         "Halal certificate on file. Expired 14 Aug 2026."),
        ("Cooking oil", "Minyak Murni Sdn Bhd", "", None,
         "No halal certificate supplied. Supplier has not responded to the last request."),
        ("Shallots", "Bawang Segar Enterprise", "HAL-2025-1042", "2027-06-30",
         "Halal certificate on file. Valid until 30 Jun 2027."),
    ]
    conn.executemany(
        """INSERT INTO certificates (case_name, supplier, item, cert_no, valid_until, notes)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [(SAMPLE_CASE, supplier, item, cert_no, valid_until, notes)
         for item, supplier, cert_no, valid_until, notes in rows],
    )
    conn.commit()


# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #

app = FastAPI(
    title="HalalReady backend",
    description="Event log + task queue used by the HalalReady agents to hand work to each other.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    init_db()


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #

class EventIn(BaseModel):
    agent: str = Field(..., description="Who is reporting the step, e.g. 'Certificate Checker'")
    step: str = Field(..., description="What just happened")
    handed_to: str = Field("", description="Agent this work was handed to, '' if nobody")


class TaskIn(BaseModel):
    to_agent: str
    from_agent: str
    what: str
    data: dict[str, Any] = Field(default_factory=dict)


class CompleteIn(BaseModel):
    result: str


# --------------------------------------------------------------------------- #
# Events
# --------------------------------------------------------------------------- #

@app.post("/events", status_code=201)
def create_event(payload: EventIn) -> dict[str, Any]:
    conn = connect()
    try:
        cur = conn.execute(
            "INSERT INTO events (time, agent, step, handed_to) VALUES (?, ?, ?, ?)",
            (now_iso(), payload.agent, payload.step, payload.handed_to or ""),
        )
        conn.commit()
        return get_event_or_404(conn, cur.lastrowid)
    finally:
        conn.close()


@app.get("/events")
def list_events(
    limit: int = Query(200, ge=1, le=5000),
    agent: str | None = None,
) -> list[dict[str, Any]]:
    conn = connect()
    try:
        sql = "SELECT * FROM events"
        args: list[Any] = []
        if agent:
            sql += " WHERE agent = ?"
            args.append(agent)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def get_event_or_404(conn: sqlite3.Connection, event_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="event not found")
    return dict(row)


@app.get("/events/view", response_class=HTMLResponse)
def events_view() -> str:
    """Plain HTML page. Auto-refreshes every 2 seconds."""
    return EVENTS_VIEW_HTML


# --------------------------------------------------------------------------- #
# Tasks
# --------------------------------------------------------------------------- #

@app.post("/tasks", status_code=201)
def create_task(payload: TaskIn) -> dict[str, Any]:
    """Create a task AND log the handoff event. The two go together."""
    conn = connect()
    try:
        cur = conn.execute(
            """INSERT INTO tasks (to_agent, from_agent, what, data, status, result)
               VALUES (?, ?, ?, ?, 'open', '')""",
            (
                payload.to_agent,
                payload.from_agent,
                payload.what,
                json.dumps(payload.data, ensure_ascii=False),
            ),
        )
        task_id = cur.lastrowid

        conn.execute(
            "INSERT INTO events (time, agent, step, handed_to) VALUES (?, ?, ?, ?)",
            (
                now_iso(),
                payload.from_agent,
                f"Handed off: {payload.what}",
                payload.to_agent,
            ),
        )
        conn.commit()
        return serialize_task(conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())
    finally:
        conn.close()


@app.get("/tasks")
def list_tasks(
    agent: str | None = Query(None, description="Filter by to_agent"),
    status: str | None = Query(None, description="open | done"),
    limit: int = Query(200, ge=1, le=5000),
) -> list[dict[str, Any]]:
    conn = connect()
    try:
        sql = "SELECT * FROM tasks"
        where: list[str] = []
        args: list[Any] = []
        if agent:
            where.append("to_agent = ?")
            args.append(agent)
        if status:
            where.append("status = ?")
            args.append(status)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id ASC LIMIT ?"
        args.append(limit)
        return [serialize_task(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


@app.get("/tasks/{task_id}")
def get_task(task_id: int) -> dict[str, Any]:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="task not found")
        return serialize_task(row)
    finally:
        conn.close()


@app.post("/tasks/{task_id}/complete")
def complete_task(task_id: int, payload: CompleteIn) -> dict[str, Any]:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="task not found")
        conn.execute(
            "UPDATE tasks SET status = 'done', result = ? WHERE id = ?",
            (payload.result, task_id),
        )
        conn.commit()
        return serialize_task(conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())
    finally:
        conn.close()


def serialize_task(row: sqlite3.Row) -> dict[str, Any]:
    task = dict(row)
    try:
        task["data"] = json.loads(task.get("data") or "{}")
    except json.JSONDecodeError:
        task["data"] = {}
    return task


# --------------------------------------------------------------------------- #
# Certificates (read-only — the sample case the agents work on)
# --------------------------------------------------------------------------- #

@app.get("/certificates")
def list_certificates(case_name: str | None = None) -> list[dict[str, Any]]:
    conn = connect()
    try:
        if case_name:
            rows = conn.execute(
                "SELECT * FROM certificates WHERE case_name = ? ORDER BY id", (case_name,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM certificates ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/cases")
def list_cases() -> list[str]:
    conn = connect()
    try:
        rows = conn.execute("SELECT DISTINCT case_name FROM certificates ORDER BY case_name").fetchall()
        return [r["case_name"] for r in rows]
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #

@app.get("/health")
def health() -> dict[str, Any]:
    conn = connect()
    try:
        counts = {
            table: conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            for table in ("events", "tasks", "certificates")
        }
    finally:
        conn.close()
    return {"status": "ok", "db": DB_PATH, "counts": counts}


# --------------------------------------------------------------------------- #
# The live view page
# --------------------------------------------------------------------------- #

EVENTS_VIEW_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>HalalReady — handoff log</title>
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 24px;
    font: 14px/1.5 ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif;
    background: #f6f7f9; color: #1a1d21;
  }
  h1 { font-size: 18px; margin: 0 0 4px; }
  .sub { color: #6b7280; font-size: 12px; margin-bottom: 18px; }
  .dot { display:inline-block; width:8px; height:8px; border-radius:50%; background:#16a34a; margin-right:6px; }
  table { width: 100%; border-collapse: collapse; background: #fff;
          border: 1px solid #e5e7eb; border-radius: 10px; overflow: hidden; }
  th, td { padding: 9px 12px; text-align: left; border-bottom: 1px solid #eef0f3; vertical-align: top; }
  th { background: #fafbfc; font-size: 11px; text-transform: uppercase;
       letter-spacing: .05em; color: #6b7280; font-weight: 600; }
  tr:last-child td { border-bottom: none; }
  tr.handoff { background: #fff8e6; }
  tr.handoff td:nth-child(3) { font-weight: 600; }
  .id { color: #9ca3af; font-variant-numeric: tabular-nums; }
  .time { color: #6b7280; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .agent { font-weight: 600; }
  .to { color: #b45309; font-weight: 600; }
  .empty { padding: 32px; text-align: center; color: #9ca3af; }
  .count { color: #6b7280; font-weight: 400; }
</style>
</head>
<body>
  <h1>HalalReady — agent handoff log <span class="count" id="count"></span></h1>
  <div class="sub"><span class="dot"></span>Live &middot; auto-refreshes every 2s &middot; <span id="updated">…</span></div>
  <table>
    <thead>
      <tr><th style="width:56px">#</th><th style="width:150px">Time</th>
          <th style="width:200px">Agent</th><th>Step</th><th style="width:170px">Handed to</th></tr>
    </thead>
    <tbody id="rows">
      <tr><td colspan="5" class="empty">Loading…</td></tr>
    </tbody>
  </table>

<script>
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function tick() {
  try {
    const res = await fetch("/events?limit=300", { cache: "no-store" });
    const events = await res.json();
    const rows = document.getElementById("rows");
    if (!events.length) {
      rows.innerHTML = '<tr><td colspan="5" class="empty">No events yet.</td></tr>';
    } else {
      rows.innerHTML = events.map(e => `
        <tr class="${e.handed_to ? "handoff" : ""}">
          <td class="id">${e.id}</td>
          <td class="time">${esc((e.time || "").replace("T", " ").slice(0, 19))}</td>
          <td class="agent">${esc(e.agent)}</td>
          <td>${esc(e.step)}</td>
          <td class="to">${e.handed_to ? "&#8594; " + esc(e.handed_to) : ""}</td>
        </tr>`).join("");
    }
    document.getElementById("count").textContent = "(" + events.length + ")";
    document.getElementById("updated").textContent = "updated " + new Date().toLocaleTimeString();
  } catch (err) {
    document.getElementById("updated").textContent = "backend unreachable";
  }
}
tick();
setInterval(tick, 2000);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
