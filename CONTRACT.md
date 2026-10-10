# HalalReady shared contract

The three layers (dashboard, backend, agents) all build against this file.
Change it only when all three people agree, and change it here first.
This version follows `HalalReady-proposal.md` (six agents, five zones).

All sample data is fictional. The app never states that anything is halal or
not halal. It only reports what is documented and what is missing.

## 1. Folder layout

```
backend/        FastAPI app, database, calculations, messaging     (Person 2)
connector/      MCP server: the tools in §5                        (Person 2)
scripts/        replay_events, test_handoff, reset_db, tunnel      (Person 2)
tests/          unit tests for calculations and messaging          (Person 2)
dashboard/      Today, Agents, Records                             (Person 1)
agents/         instructions, one file per agent                   (Person 3)
rules/          rule files; recognised_certifiers.json             (Person 3)
sample_case/    fictional invoices, certificates, zone photos      (Person 3)
```

## 2. Running it

```
python -m venv .venv
.venv\Scripts\pip install -r backend/requirements.txt -r connector/requirements.txt
copy env.example .env

.venv\Scripts\python -m uvicorn backend.app:app --reload --port 8000   # backend, http://localhost:8000/docs
.venv\Scripts\python scripts/replay_events.py --reset                   # fake run for the dashboard
.venv\Scripts\python scripts/test_handoff.py                            # two agents through the real connector
.venv\Scripts\python scripts/reset_db.py                                # one-command demo reset
.venv\Scripts\python scripts/tunnel.py                                  # ngrok for supplier replies
.venv\Scripts\python -m pytest tests
```

Replay options: `--finish` continues through approvals, replies and the pack;
`--upkeep` jumps the date 123 days and wakes Renewal Watch; `--from-run N`
re-posts the agent events of a recorded run (sped up, `--speed 4`).

**Registering the connector in WorkBuddy:** see
`connector/workbuddy-mcp.example.json`. Stdio: command = the venv's Python,
args = `connector/server.py`. HTTP: run `python connector/server.py --http`
and use `http://127.0.0.1:8001/mcp`.

## 3. Fixed values

| Name | Allowed values |
|---|---|
| agent | `coordinator`, `certificate_checker`, `supplier_chaser`, `document_writer`, `onsite_inspector`, `renewal_watch` |
| event author | any agent, plus `owner` (dashboard actions) and `system` (date triggers, backend) |
| event status | `ok`, `problem`, `attention`, `action`, `info` |
| certificate status (calculated) | `valid`, `expiring`, `expired`, `missing`, `unrecognised_issuer` |
| ingredient kind / proof | `processed`, `natural` / `halal_certificate`, `source_document` |
| file category (input tray) | `company`, `products`, `suppliers`, `site`; `null` = not sorted yet |
| file kind | `invoice`, `certificate`, `recipe`, `photo`, `registration`, `label`, `other` |
| zone | `store`, `processing`, `packing`, `cleaning`, `waste` |
| zone status (calculated) | `unchecked`, `clear`, `issue` |
| site finding severity | `ok` (checked, nothing found), `attention`, `problem` |
| task status | `open`, `in_progress` (picked up), `done` |
| approval kind / status | `message`, `document` / `pending`, `approved`, `rejected`, `sent`, `failed`, `replied` |
| message channel | `whatsapp`, `telegram`, `manual` |
| required documents (`doc_type`) | `halal_policy`, `ingredient_control`, `traceability` |

Dates are `YYYY-MM-DD`. Timestamps are ISO 8601 with +08:00. IDs are integers.

## 4. Data

Tables (see `backend/database.py`): `businesses`, `runs`, `products`,
`suppliers`, `ingredients`, `product_ingredients`, `files` (with `category`
and `zone`), `certificates` (an ingredient can have several; the latest
counts), `documents` (one row per `doc_type`, `version` goes up on each save),
`site_findings` (with `question` / `answer` for the owner), `tasks` (the agent
task board), `approvals` (owner approval cards and the messages they send),
`events` (with `handed_to`), `packs`, `settings`.

## 5. Calculations (backend only, never the agents)

"Today" is the demo override when set (`PUT /clock`), otherwise the real date.

Certificate status from the ingredient's latest certificate:

1. no certificate on file → `missing`
2. issuer known to be unrecognised → `unrecognised_issuer`
3. expiry before today → `expired`
4. expiry within 60 days → `expiring`
5. otherwise, or no expiry (source document) → `valid`

`issuer_recognised` left empty is looked up in `rules/recognised_certifiers.json`
(a list of names, or objects with `name` / `short_name` / `aliases`). If the
file is missing it stays unknown, which does not count against the ingredient.

An ingredient is **covered** when `valid` or `expiring`. A zone is **clear**
when it has at least one finding and no open `attention`/`problem` finding.

```
readiness = round(100 × (covered ingredients + clear zones + approved required documents)
                      / (all ingredients + 5 zones + 3 required documents))
```

The replayed sample case gives (10 + 3 + 0) / (13 + 5 + 3) = **62%**.

**Date trigger:** when the date changes, every certificate that is expiring or
expired gets a task for `renewal_watch` (once per certificate), the event is
posted as `system → renewal_watch`, and the owner gets a phone alert.

## 6. Connector tools (what agents can call)

`BUSINESS_ID` comes from the connector's environment, so agents never pass it.

| Tool | Input | Returns |
|---|---|---|
| `post_event` | `agent`, `label` (≤ 8 words), `status`, `handed_to?` | event |
| `create_task` | `from_agent`, `assignee`, `title`, `detail?`, `payload?` | task; also posts the handoff event |
| `get_my_tasks` | `agent` | open/in-progress tasks (marks them picked up) |
| `complete_task` | `task_id`, `agent`, `result?` | task; posts a `Done: …` event |
| `get_case` | | business, today, readiness, products, suppliers, ingredients with status, documents, zones, files |
| `get_files` | `category?`, `unsorted_only?` | files with `local_path` |
| `read_file` | `file_id` | image content, text, or local path |
| `sort_file` | `file_id`, `category`, `kind?`, `zone?`, `supplier_name?` | file |
| `get_certificates` | | every ingredient with status and days to expiry |
| `save_ingredients` | list of `{name, brand?, kind, proof_type, supplier_name?, supplier_phone?, product_names?, found_on_site?}` | ids (upsert by name) |
| `save_certificate` | `ingredient_id` or `ingredient_name`, `issuer`, `cert_number?`, `expiry_date?`, `issuer_recognised?`, `file_id?` | calculated status |
| `save_document` | `doc_type`, `body` (Markdown), `title?` | document (new version if it exists) |
| `save_site_finding` | `zone`, `severity`, `title`, `detail?`, `question?`, `photo_file_id?` | finding and zone status |
| `request_approval` | `kind`, `agent`, message: supplier + `ingredient_*` + `body_ms`/`body_en`; document: `document_id` or `doc_type` | approval card |
| `set_status` | `sentence` | the Coordinator's status sentence for the Today tab |
| `assemble_pack` | | pack items ready / missing, download URL |

Rules for agents:

- Call `post_event` after every step, with a label of 8 words or fewer.
- Hand work over with `create_task`; never ask another agent in free text.
- Never send a message. `request_approval`; the owner approves in the dashboard.
- Never calculate dates or scores. Read them from `get_case` or `get_certificates`.

## 7. One event

```json
{
  "id": 41, "business_id": 1, "run_id": 3,
  "agent": "certificate_checker", "handed_to": "supplier_chaser",
  "label": "Chilli paste certificate expired",
  "status": "problem", "task_id": 12, "approval_id": null,
  "created_at": "2026-10-10T09:14:05+08:00"
}
```

**Live stream:** `GET /business/{id}/stream` (server-sent events). Each
message has `id:` = event id and `data:` = the event JSON. With no position it
sends the last 100 events, then live ones; `?after_id=N` or the browser's
automatic `Last-Event-ID` resumes after N. `GET /runs/{id}/stream` is the same
for one run. The dashboard should refetch the tab it shows when an event
arrives; every state change of interest posts an event.

## 8. Backend endpoints (what the dashboard calls)

| Method and path | Purpose |
|---|---|
| `GET /business/{id}/overview` | Today tab: readiness, status sentence, journey, trays, problems, next renewal |
| `GET /business/{id}/agents` | per-agent state (`working`, `waiting`, `idle`), last event, recent handoffs |
| `GET /business/{id}/agents/{agent}/events` | an agent's recent steps |
| `GET /business/{id}/feed` | owner feed: `needs_you`, `working_on`, `done` |
| `GET /business/{id}/events?after_id=` | events as a list |
| `GET /business/{id}/stream` | live events (§7) |
| `GET /business/{id}/ingredients`, `GET /ingredients/{id}` | Records: Ingredients |
| `GET /business/{id}/suppliers`, `PATCH /suppliers/{id}` | Records: Suppliers; set the demo phone / Telegram chat |
| `GET /business/{id}/documents`, `GET/PATCH /documents/{id}` | Records: Documents; owner edits a draft |
| `GET /business/{id}/site`, `PATCH /site-findings/{id}` | Records: Site; resolve or answer a question |
| `GET /business/{id}/pack`, `POST …/pack`, `GET …/pack/download` | Records: Pack checklist, assemble, download zip |
| `GET /business/{id}/approvals?status=` | approval cards |
| `POST /approvals/{id}/approve` | approve a document, or approve **and send** a message (optional edited `body_ms`/`body_en`) |
| `POST /approvals/{id}/reject` | send back to the agent with `comment` (creates a task) |
| `POST /approvals/{id}/fallback` | re-send on Telegram now |
| `POST /business/{id}/files` | upload (`files[]`, optional `category`, `kind`, `zone`); no category = Coordinator sorts |
| `GET /files/{id}/content` | the file itself (thumbnails) |
| `POST /business/{id}/runs` | start a run (`mode`: `prepare`/`upkeep`) |
| `GET/PUT/DELETE /clock` | the "today" override (`{"today": "2027-02-10"}` or `{"add_days": 120}`) |
| `GET /messaging/status` | channel, what is configured, tunnel URL, last Telegram chat id |
| `POST /admin/reset` | empty everything and reseed |
| `POST /webhooks/twilio`, `POST /webhooks/telegram` | incoming supplier replies (through the tunnel) |

Interactive docs: `http://localhost:8000/docs`.

## 9. Messaging

- `MESSAGING_CHANNEL=manual` (default) sends nothing; the card shows the text.
- `whatsapp`: Twilio WhatsApp. If Twilio refuses, or there is no reply within
  `FALLBACK_AFTER_MINUTES` (120), the message is re-sent on Telegram to the
  supplier's `telegram_chat_id`, or to `TELEGRAM_FALLBACK_CHAT_ID`.
- `telegram`: Telegram only.
- A reply is matched to the supplier and their last message. An attachment is
  filed in the Suppliers tray and handed to the Certificate Checker as a task.
- Through the tunnel only `/webhooks/*` answers. Twilio requests are checked
  against their signature, Telegram's against `TELEGRAM_WEBHOOK_SECRET`.

## 10. Still to confirm

- Whether WorkBuddy reaches a localhost connector over stdio or HTTP (both work).
- Whether WorkBuddy accepts image input through `read_file`.
- The real pack section order, matched to the current MYeHALAL form.
- Zone criteria from MPPHM and MS 1500:2019 (Person 3).
