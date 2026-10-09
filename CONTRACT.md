# HalalReady shared contract

The three layers (dashboard, backend, agents) all build against this file.
Change it only when all three people agree, and change it here first.

All sample data is fictional. The app never states that anything is halal or
not halal. It only reports what is documented and what is missing.

## 1. Folder layout

```
halalready/
  backend/        FastAPI app, database, calculations     (Person 2)
  connector/      MCP server exposing the tools in §5     (Person 2)
  dashboard/      Web app with the six screens            (Person 1)
  agents/         Agent instructions, one file per agent  (Person 3)
  rules/          ingredient_rules.json, recognised_certifiers.json (Person 3)
  sample_case/    Fictional invoices, certificates, site clip       (Person 3)
  CONTRACT.md
  .env.example
  .gitignore
```

## 2. Fixed values

Use these exact strings everywhere.

| Name | Allowed values |
|---|---|
| agent | `coordinator`, `paper`, `place`, `upkeep` |
| event status | `ok`, `problem`, `attention`, `action`, `info` |
| certificate status (calculated) | `valid`, `expiring`, `expired`, `missing`, `unrecognised_issuer` |
| ingredient kind | `processed`, `natural` |
| proof type | `halal_certificate`, `source_document` |
| finding category | `certificate`, `site`, `upkeep` |
| finding severity | `problem`, `attention`, `info` |
| finding status | `open`, `resolved` |
| task type | `supplier_message`, `site_fix` |
| task status | `draft`, `approved`, `sent`, `done` |
| task channel | `whatsapp`, `telegram`, `manual` |
| file kind | `invoice`, `certificate`, `label_photo`, `site_clip`, `other` |
| site area | `receiving`, `dry_store`, `production`, `packing` |

Dates are `YYYY-MM-DD`. Timestamps are ISO 8601 with timezone. IDs are integers.

## 3. Database tables

**businesses**: `id`, `name`, `halal_cert_number` (nullable), `halal_cert_expiry` (nullable)

**products**: `id`, `business_id`, `name`

**suppliers**: `id`, `business_id`, `name`, `contact_name`, `phone`, `email`

**ingredients**: `id`, `business_id`, `name`, `brand`, `supplier_id`, `kind`, `proof_type`

**product_ingredients**: `product_id`, `ingredient_id`

**files**: `id`, `business_id`, `kind`, `filename`, `path`, `uploaded_at`

**certificates**: `id`, `ingredient_id`, `issuer`, `cert_number`, `expiry_date` (nullable for source documents), `issuer_recognised` (true, false or null if not checked), `file_id`

**runs**: `id`, `business_id`, `started_at`, `finished_at` (nullable), `sim_date`

**events**: `id`, `run_id`, `agent`, `label`, `status`, `finding_id` (nullable), `created_at`

**findings**: `id`, `run_id`, `agent`, `category`, `severity`, `title`, `detail`, `ingredient_id` (nullable), `area` (nullable), `status`, `created_at`

**tasks**: `id`, `finding_id`, `type`, `supplier_id` (nullable), `channel`, `body_ms`, `body_en`, `assignee` (nullable), `due_date` (nullable), `status`, `created_at`

## 4. Calculations (backend only, never the agents)

"Today" is the run's `sim_date` if set, otherwise the real date.

Certificate status for an ingredient:

1. No certificate on file → `missing`
2. `issuer_recognised` is false → `unrecognised_issuer`
3. `expiry_date` before today → `expired`
4. `expiry_date` within 60 days of today → `expiring`
5. Otherwise → `valid`

An ingredient counts as **covered** when its status is `valid` or `expiring`.
A site area counts as **clear** when it has no open `site` finding.

```
readiness = round(100 × (covered ingredients + clear areas)
                      / (all ingredients + 4 areas))
```

For the sample case this gives (9 + 2) / (12 + 4) = 69%. The UI draft shows
62% as a placeholder; use the calculated value.

## 5. Connector tools (what agents can call)

| Tool | Input | Returns |
|---|---|---|
| `get_case` | `business_id` | business, products, ingredients, suppliers, certificates with calculated status, list of files |
| `save_ingredients` | `business_id`, list of `{name, brand, supplier_name, kind, proof_type, product_names[]}` | saved ingredient ids |
| `save_certificate` | `ingredient_id`, `issuer`, `cert_number`, `expiry_date`, `issuer_recognised`, `file_id` | certificate id and calculated status |
| `list_certificates` | `business_id` | every ingredient with status and days to expiry |
| `save_finding` | `run_id`, `agent`, `category`, `severity`, `title`, `detail`, `ingredient_id?`, `area?` | finding id |
| `create_task` | `finding_id`, `type`, `supplier_id?`, `body_ms`, `body_en`, `assignee?`, `due_date?` | task id (always created as `draft`) |
| `post_event` | `run_id`, `agent`, `label`, `status`, `finding_id?` | event id |

Rules for agents:

- Call `post_event` after every step, with a label of 8 words or fewer.
- Never send a message. Only `create_task`; the owner approves in the dashboard.
- Never calculate dates or scores. Read them from `get_case` or `list_certificates`.

## 6. One agent step (event)

```json
{
  "id": 41,
  "run_id": 3,
  "agent": "paper",
  "label": "Shrimp paste certificate expired Aug 2026",
  "status": "problem",
  "finding_id": 12,
  "created_at": "2026-10-10T09:14:05+08:00"
}
```

The backend pushes each new event to the dashboard over a live stream at
`GET /runs/{run_id}/stream` (server-sent events), one JSON object per message.

## 7. Backend endpoints (what the dashboard calls)

| Method and path | Purpose |
|---|---|
| `GET /business/{id}/overview` | readiness, counters, next steps |
| `GET /business/{id}/ingredients` | all ingredients with status and products |
| `GET /ingredients/{id}` | one ingredient with certificate and history |
| `POST /business/{id}/files` | upload a file with its `kind` |
| `POST /business/{id}/runs` | start a run, optional `sim_date`; returns `run_id` |
| `GET /runs/{id}` | run with its events and findings so far |
| `GET /runs/{id}/stream` | live events |
| `GET /business/{id}/findings` | open findings |
| `GET /business/{id}/tasks` | tasks, filter by `status` |
| `PATCH /tasks/{id}` | edit body, approve, mark sent or done |
| `POST /tasks/{id}/send` | send an approved message through the channel |
| `GET /business/{id}/site-check` | areas with status and findings |
| `GET /business/{id}/pack` | pack checklist with item status |
| `POST /webhooks/messaging` | incoming supplier reply |

## 8. Still to confirm

- Whether the hackathon account lets the dashboard start a WorkBuddy run. If
  not, start runs by telling WorkBuddy directly with the `run_id`.
- Whether WorkBuddy accepts video. If not, the backend extracts still frames
  and stores them as `label_photo` / `site_clip` frames.
- The real pack sections, matched to the current MYeHALAL form.
