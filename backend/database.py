"""
HalalReady Backend — Database layer
All tables from CONTRACT.md §3, plus documents, site_findings, approvals
from the proposal.  Includes the 'handed_to' column on events.
"""

import aiosqlite, os
from datetime import date, datetime, timezone, timedelta

MYT = timezone(timedelta(hours=8))
DB_PATH = os.getenv("DATABASE_PATH", "./backend/halalready.db")


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db():
    db = await get_db()
    await db.executescript(SCHEMA)
    await db.commit()
    await db.close()


SCHEMA = """
-- ── core entities ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS businesses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    halal_cert_number TEXT,
    halal_cert_expiry TEXT          -- YYYY-MM-DD or NULL
);

CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    name        TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS suppliers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id  INTEGER NOT NULL REFERENCES businesses(id),
    name         TEXT    NOT NULL,
    contact_name TEXT,
    phone        TEXT,
    email        TEXT
);

CREATE TABLE IF NOT EXISTS ingredients (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    name        TEXT    NOT NULL,
    brand       TEXT,
    supplier_id INTEGER REFERENCES suppliers(id),
    kind        TEXT    NOT NULL CHECK(kind IN ('processed','natural')),
    proof_type  TEXT    NOT NULL CHECK(proof_type IN ('halal_certificate','source_document'))
);

CREATE TABLE IF NOT EXISTS product_ingredients (
    product_id    INTEGER NOT NULL REFERENCES products(id),
    ingredient_id INTEGER NOT NULL REFERENCES ingredients(id),
    PRIMARY KEY (product_id, ingredient_id)
);

-- ── files & certificates ───────────────────────────────────────────

CREATE TABLE IF NOT EXISTS files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    kind        TEXT    NOT NULL CHECK(kind IN ('invoice','certificate','label_photo','site_clip','other')),
    filename    TEXT    NOT NULL,
    path        TEXT    NOT NULL,
    uploaded_at TEXT    NOT NULL    -- ISO 8601
);

CREATE TABLE IF NOT EXISTS certificates (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ingredient_id     INTEGER NOT NULL REFERENCES ingredients(id),
    issuer            TEXT    NOT NULL,
    cert_number       TEXT    NOT NULL,
    expiry_date       TEXT,           -- YYYY-MM-DD, nullable for source documents
    issuer_recognised INTEGER,        -- 1=true, 0=false, NULL=not checked
    file_id           INTEGER REFERENCES files(id)
);

-- ── runs, events, findings, tasks ──────────────────────────────────

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    started_at  TEXT    NOT NULL,     -- ISO 8601
    finished_at TEXT,
    sim_date    TEXT                  -- YYYY-MM-DD override for "today"
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES runs(id),
    agent       TEXT    NOT NULL,
    label       TEXT    NOT NULL,
    status      TEXT    NOT NULL CHECK(status IN ('ok','problem','attention','action','info')),
    finding_id  INTEGER REFERENCES findings(id),
    handed_to   TEXT,                 -- agent name this event hands work to (proposal §5)
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS findings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        INTEGER NOT NULL REFERENCES runs(id),
    agent         TEXT    NOT NULL,
    category      TEXT    NOT NULL CHECK(category IN ('certificate','site','upkeep')),
    severity      TEXT    NOT NULL CHECK(severity IN ('problem','attention','info')),
    title         TEXT    NOT NULL,
    detail        TEXT,
    ingredient_id INTEGER REFERENCES ingredients(id),
    area          TEXT    CHECK(area IS NULL OR area IN ('receiving','dry_store','production','packing')),
    status        TEXT    NOT NULL DEFAULT 'open' CHECK(status IN ('open','resolved')),
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    finding_id  INTEGER REFERENCES findings(id),
    type        TEXT    NOT NULL CHECK(type IN ('supplier_message','site_fix')),
    supplier_id INTEGER REFERENCES suppliers(id),
    channel     TEXT    NOT NULL DEFAULT 'manual' CHECK(channel IN ('whatsapp','telegram','manual')),
    body_ms     TEXT,
    body_en     TEXT,
    assignee    TEXT,
    due_date    TEXT,
    status      TEXT    NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','approved','sent','done')),
    created_at  TEXT    NOT NULL
);

-- ── documents & approvals (proposal §6) ────────────────────────────

CREATE TABLE IF NOT EXISTS documents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    title       TEXT    NOT NULL,     -- e.g. "Halal Policy", "Ingredient Control"
    version     INTEGER NOT NULL DEFAULT 1,
    body        TEXT,                 -- markdown or plain text
    status      TEXT    NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','pending_approval','approved','rejected')),
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS site_findings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id   INTEGER NOT NULL REFERENCES businesses(id),
    run_id        INTEGER REFERENCES runs(id),
    area          TEXT    NOT NULL CHECK(area IN ('receiving','dry_store','production','packing')),
    severity      TEXT    NOT NULL CHECK(severity IN ('problem','attention','info')),
    title         TEXT    NOT NULL,
    detail        TEXT,
    photo_file_id INTEGER REFERENCES files(id),
    status        TEXT    NOT NULL DEFAULT 'open' CHECK(status IN ('open','resolved')),
    created_at    TEXT    NOT NULL,
    resolved_at   TEXT
);

CREATE TABLE IF NOT EXISTS approvals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item_type   TEXT    NOT NULL,     -- 'task', 'document', 'message'
    item_id     INTEGER NOT NULL,
    action      TEXT    NOT NULL CHECK(action IN ('approve','reject')),
    comment     TEXT,
    decided_by  TEXT    NOT NULL DEFAULT 'owner',
    decided_at  TEXT    NOT NULL
);
"""
