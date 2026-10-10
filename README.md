# HalalReady — agent handoff test rig

A minimal, runnable proof that **two agents can hand work to each other through a custom
MCP server**. Built for a small Malaysian food manufacturer preparing halal certification
paperwork.

One agent (**Certificate Checker**) reads supplier certificates, flags the expired and
missing ones, and creates tasks. The other (**Supplier Chaser**) picks those tasks up,
drafts a polite WhatsApp-style message per supplier, and completes the task with the draft
as the result.

> **This build makes no halal determination.** It moves paperwork and drafts messages.
> Nothing is ever sent to a supplier — every draft is marked `[Not sent — draft only]`.

## Scope: this is the "two-agent connector test" from the proposal

`HalalReady-proposal.md` (updated 10 Oct 2026) is the team's current plan. It supersedes
`CONTRACT.md`, which still describes the older four-agent version (Coordinator, Paper,
Place, Upkeep). **Neither file is modified by this branch.**

This rig is exactly the proposal's first milestone (§9) — *"two agents (Certificate Checker
→ Supplier Chaser) hand off a task through the connector, visible on the events page"* — and
next action 2 in §12. The agent names and tool names match the proposal:

- **§5** names the two agents **Certificate Checker** and **Supplier Chaser**, with the
  handoff "expired or missing certificates". That is what `agents/` implements.
- **§6** lists the connector's first tools as `post_event`, `create_task`, `get_my_tasks`,
  `complete_task`, `get_certificates`. All five are in `mcp/server.py`.
- **§6** says events carry `handed_to` "so the dashboard graph is drawn from real data".
  The `events` table has that column, and `/events/view` already highlights those rows.
- **§6** says the backend "does all date, status and score calculations". The checker
  computes nothing itself; `valid_until` comes from the backend.

One deliberate difference: the MCP server lives in `mcp/` here rather than `connector/` as
§9 specifies, because the brief this was written to named `mcp/`. If you would rather it sit
in `connector/`, it is a one-line `git mv`.

Still to build for the real connector: `get_files`, `save_ingredients`, `save_document`,
`save_site_finding`, `request_approval`, plus the `approvals` table and the
`dashboard/`, `rules/` and `sample_case/` folders — all untouched and free.

```
certificate-checker  --create_task-->  MCP server (FastMCP, :8100)  -->  SQLite
        ^                                                                  |
        |                                                        events + tasks
        |                                                                  |
        +-----------------  supplier-chaser  <--get_my_tasks---------------+
                                  |
                     complete_task(draft)  -->  [Not sent — draft only]
```

## Layout

```
halalready/
├── backend/
│   └── main.py             FastAPI + SQLite. Tables: events, tasks, certificates.
├── mcp/
│   └── server.py           FastMCP streamable HTTP on :8100. Wraps the backend.
├── agents/
│   ├── certificate-checker.md   paste into a WorkBuddy expert
│   └── supplier-chaser.md       paste into a WorkBuddy expert
├── smoke_test.py           end-to-end test over the real MCP protocol
├── requirements.txt
└── README.md
```

## 1. Install

```bash
cd halalready
python -m venv .venv
source .venv/Scripts/activate      # Windows Git Bash
# source .venv/bin/activate        # macOS / Linux
pip install -r requirements.txt
```

## 2. Run the backend (port 8000)

```bash
cd backend
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

On first start it creates `backend/halalready.db` and seeds the sample case. You should see
`Application startup complete`.

Check it:

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok","db":"...","counts":{"events":0,"tasks":0,"certificates":3}}
```

**Watch handoffs live:** open <http://127.0.0.1:8000/events/view> — a plain HTML page that
auto-refreshes every 2 seconds. Handoff rows are highlighted and show `→ Supplier Chaser`.

## 3. Run the MCP server (port 8100)

In a **second terminal**, with the backend still running:

```bash
cd mcp
python server.py
# or, to point somewhere else:
# python server.py --port 8100 --backend http://127.0.0.1:8000
```

It prints its own URL on startup:

```
HalalReady MCP server
  sdk      -> mcp 2.x (MCPServer)
  backend  -> http://127.0.0.1:8000
  MCP URL  -> http://127.0.0.1:8100/mcp
  live log -> http://127.0.0.1:8000/events/view
```

> Works with both MCP SDK majors. `mcp` 1.x ships `FastMCP`; `mcp` 2.x renamed it to
> `MCPServer`. `mcp/server.py` detects whichever is installed, so you do not need to pin.

## 4. Add it in WorkBuddy Connectors

**MCP URL to paste into WorkBuddy:**

```
http://127.0.0.1:8100/mcp
```

Steps:

1. Keep both servers running — WorkBuddy connects to a live URL, it does not start them.
2. Open **Connectors** from the plus menu in the bottom-left of the chat window.
3. Use the **custom connectors** entry at the top-right of the connector management page.
4. Add a server named `halalready` with the URL above.
5. Click **Trust** on the new server. It will not activate until you do.
6. Ask WorkBuddy *"what tools do you have?"* — you should see `get_certificates`,
   `post_event`, `create_task`, `get_my_tasks`, `complete_task`, `get_timeline`,
   `backend_health`.

You can also write it straight into `~/.workbuddy-ai/mcp.json` (older docs may say
`~/.workbuddy/mcp.json`) and restart, then Trust it:

```json
{
  "mcpServers": {
    "halalready": {
      "url": "http://127.0.0.1:8100/mcp"
    }
  }
}
```

If you would rather WorkBuddy launch the MCP server itself, use `command` + `args` instead
of `url` — but the backend on :8000 still has to be running separately.

## 5. Test steps

### 5a. Automated — no LLM, ~2 seconds

With both servers up:

```bash
python smoke_test.py
```

It speaks the real MCP protocol, so if this passes, WorkBuddy can reach the same tools. It
replays the whole loop and checks 18 things, ending with:

```
RESULT: all checks passed — the two agents handed work to each other.
```

Then open <http://127.0.0.1:8000/events/view> and watch the handoff rows.

### 5b. Manual — the actual agent test

1. Create a WorkBuddy expert and paste `agents/certificate-checker.md` as its instructions.
2. In a new conversation with that expert, say:
   > Check the certificates for Mak Teh Sambal (sample).

   Expect: a table of 3 certificates, 2 flagged (1 expired, 1 missing), 2 tasks handed to
   `Supplier Chaser`, and no halal claim anywhere. Watch the tasks appear on the live page.

3. Create a second expert and paste `agents/supplier-chaser.md`.
4. In a new conversation with that expert, say:
   > Get your tasks and draft the messages.

   Expect: 2 drafts, one per supplier, each ending `[Not sent — draft only]`, and both tasks
   showing `status: done` with the draft in `result`.

5. Verify the handoff happened through the MCP server, not around it:

```bash
curl "http://127.0.0.1:8000/tasks?agent=Supplier%20Chaser"
curl "http://127.0.0.1:8000/tasks/1"     # result holds the draft
curl "http://127.0.0.1:8000/events?limit=20"
```

### The sample case

`Mak Teh Sambal (sample)` — 3 suppliers, checked against today's date:

| Item | Supplier | Cert no. | Valid until | Expected |
|---|---|---|---|---|
| Chilli paste | Syarikat Cili Maju | HAL-2024-8871 | 2026-08-14 | **expired** → task |
| Cooking oil | Minyak Murni Sdn Bhd | *(none)* | *(none)* | **missing** → task |
| Shallots | Bawang Segar Enterprise | HAL-2025-1042 | 2027-06-30 | valid → log only |

## MCP tools

| Tool | What it does |
|---|---|
| `get_certificates(case_name="")` | Read the sample case's certificates |
| `post_event(agent, step, handed_to="")` | Log one step to the shared timeline |
| `create_task(to_agent, from_agent, what, data)` | Hand work over. **Also logs the handoff event** |
| `get_my_tasks(agent)` | Open tasks addressed to this agent |
| `complete_task(task_id, result)` | Finish a task and hand back the result |
| `get_timeline(limit=50)` | Read back recent events |
| `backend_health()` | Check the backend is reachable |

## Backend API

| Method | Path | Notes |
|---|---|---|
| `POST` | `/events` | `{agent, step, handed_to}` |
| `GET` | `/events?limit=&agent=` | Newest first |
| `GET` | `/events/view` | HTML, auto-refresh 2s |
| `POST` | `/tasks` | `{to_agent, from_agent, what, data}` — creates the handoff event too |
| `GET` | `/tasks?agent=&status=` | `status` is `open` or `done` |
| `GET` | `/tasks/{id}` | |
| `POST` | `/tasks/{id}/complete` | `{result}` |
| `GET` | `/certificates?case_name=` | Read-only seed data |
| `GET` | `/cases` | |
| `GET` | `/health` | Row counts |

`tasks.data` is stored as JSON and returned as an object. `tasks.status` is `open` or `done`.

## Resetting

The smoke test appends rows every run. To start clean, stop the servers and delete the
database — it is recreated and re-seeded on next startup:

```bash
rm backend/halalready.db backend/halalready.db-wal backend/halalready.db-shm
```

## Notes and limits

- **Drafts only.** No messaging integration, by design. The chaser writes text into a task
  result and stops.
- **No halal determination.** The checker reports what a certificate says and whether it is
  expired, missing, or valid. That is all.
- **Localhost only.** Both servers bind `127.0.0.1`. If WorkBuddy cannot reach the MCP URL,
  start the MCP server with `--host 0.0.0.0` (this exposes it on your LAN — dev only).
- **Ports** 8000 and 8100 are hardcoded defaults, both overridable with `--port` /
  `HALALREADY_BACKEND` / `HALALREADY_MCP_PORT`.
- **`certificates` is not in the original spec.** The checker needed something to check, so
  the sample case lives in a small read-only table. Swap it for a real data source later.
