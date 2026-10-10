"""
HalalReady backend: database layer (SQLite).

Tables follow the proposal (§6 Data): files (with category), ingredients,
suppliers, certificates, documents, site_findings, tasks, events (with
handed_to), approvals. Plus businesses, products, runs, packs and settings,
which the rest of the app needs.
"""

import hashlib
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

MYT = timezone(timedelta(hours=8))


def _resolve(path_str: str) -> Path:
    p = Path(path_str)
    return p if p.is_absolute() else (ROOT / p).resolve()


DB_PATH = _resolve(os.getenv("DATABASE_PATH", "./backend/halalready.db"))
UPLOAD_DIR = _resolve(os.getenv("UPLOAD_DIR", "./backend/uploads"))


def now_iso() -> str:
    return datetime.now(MYT).isoformat(timespec="seconds")


# ── fixed values (see CONTRACT.md §2) ────────────────────────────────

AGENTS = [
    "coordinator",
    "certificate_checker",
    "supplier_chaser",
    "document_writer",
    "onsite_inspector",
    "renewal_watch",
    "auditor",
]
# Event authors that are not agents: the owner's dashboard actions and the
# backend itself (date jumps, incoming replies, fallbacks).
ACTORS = AGENTS + ["owner", "system"]

EVENT_STATUSES = ["ok", "problem", "attention", "action", "info"]
FILE_CATEGORIES = ["company", "products", "suppliers", "site"]
FILE_KINDS = ["invoice", "certificate", "recipe", "photo", "registration", "label", "other"]
ZONES = ["store", "processing", "packing", "cleaning", "waste"]
REQUIRED_DOCUMENTS = {
    "halal_policy": "Halal Policy",
    "ingredient_control": "Ingredient Control Procedure",
    "traceability": "Traceability Procedure",
}


@asynccontextmanager
async def connect():
    """Open a connection, commit on success, always close."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys=ON")
    await db.execute("PRAGMA busy_timeout=5000")
    try:
        yield db
        await db.commit()
    finally:
        await db.close()


SCHEMA_VERSION = 7


async def init_db():
    """Create the tables. A database from an older schema is rebuilt (it only held sample data)."""
    async with connect() as db:
        await db.execute("PRAGMA journal_mode=WAL")
        version = (await db.execute_fetchall("PRAGMA user_version"))[0][0]
        tables = await db.execute_fetchall("SELECT name FROM sqlite_master WHERE type='table'")
        if version < SCHEMA_VERSION and tables:
            await db.execute("PRAGMA foreign_keys=OFF")
            for r in tables:
                if not r["name"].startswith("sqlite_"):
                    await db.execute(f'DROP TABLE IF EXISTS "{r["name"]}"')
        await db.executescript(SCHEMA)
        await db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


async def reset_db():
    """
    Drop every table and recreate the schema. Works while the server runs.
    Settings survive (tunnel URL, Telegram chat), except the date override.
    """
    async with connect() as db:
        await db.execute("PRAGMA foreign_keys=OFF")
        rows = await db.execute_fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != 'settings'"
        )
        for r in rows:
            await db.execute(f'DROP TABLE IF EXISTS "{r["name"]}"')
        await db.executescript(SCHEMA)
        await db.execute("DELETE FROM settings WHERE key = 'today_override'")


async def fetch_all(db, sql: str, params=()) -> list[dict]:
    return [dict(r) for r in await db.execute_fetchall(sql, params)]


async def fetch_one(db, sql: str, params=()) -> dict | None:
    rows = await db.execute_fetchall(sql, params)
    return dict(rows[0]) if rows else None


def fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def insert(db, table: str, values: dict) -> int:
    if table == "files" and "sha256" not in values and values.get("path"):
        # Every stored file is fingerprinted once; reads are refused if the bytes ever change.
        values = {**values, "sha256": fingerprint(UPLOAD_DIR / values["path"])}
    cols = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    cur = await db.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(values.values()))
    return cur.lastrowid


async def update(db, table: str, row_id: int, values: dict):
    if not values:
        return
    sets = ", ".join(f"{k} = ?" for k in values)
    await db.execute(f"UPDATE {table} SET {sets} WHERE id = ?", (*values.values(), row_id))


def _check(col: str, values: list[str], nullable: bool = False) -> str:
    allowed = ",".join(f"'{v}'" for v in values)
    if nullable:
        return f"CHECK({col} IS NULL OR {col} IN ({allowed}))"
    return f"CHECK({col} IN ({allowed}))"


SCHEMA = f"""
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS businesses (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    name                   TEXT NOT NULL,
    owner_name             TEXT,
    owner_phone            TEXT,          -- E.164, for WhatsApp alerts
    owner_telegram_chat_id TEXT,
    halal_cert_number      TEXT,
    halal_cert_expiry      TEXT,          -- YYYY-MM-DD
    status_sentence        TEXT,          -- written by the Coordinator
    status_updated_at      TEXT,
    is_sample              INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    mode        TEXT NOT NULL DEFAULT 'prepare' {_check('mode', ['prepare', 'upkeep'])},
    started_at  TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    name        TEXT NOT NULL,
    UNIQUE (business_id, name)
);

CREATE TABLE IF NOT EXISTS suppliers (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id      INTEGER NOT NULL REFERENCES businesses(id),
    name             TEXT NOT NULL,
    contact_name     TEXT,
    phone            TEXT,               -- E.164, used for WhatsApp
    email            TEXT,
    telegram_chat_id TEXT,               -- used for the Telegram fallback
    language         TEXT NOT NULL DEFAULT 'ms' {_check('language', ['ms', 'en'])},
    UNIQUE (business_id, name)
);

CREATE TABLE IF NOT EXISTS ingredients (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    name        TEXT NOT NULL,
    brand       TEXT,
    supplier_id INTEGER REFERENCES suppliers(id),
    kind        TEXT NOT NULL {_check('kind', ['processed', 'natural'])},
    proof_type  TEXT NOT NULL {_check('proof_type', ['halal_certificate', 'source_document'])},
    source      TEXT NOT NULL DEFAULT 'declared' {_check('source', ['declared', 'found_on_site'])},
    created_at  TEXT NOT NULL,
    UNIQUE (business_id, name)
);

CREATE TABLE IF NOT EXISTS product_ingredients (
    product_id    INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    ingredient_id INTEGER NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
    PRIMARY KEY (product_id, ingredient_id)
);

CREATE TABLE IF NOT EXISTS files (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id  INTEGER NOT NULL REFERENCES businesses(id),
    category     TEXT {_check('category', FILE_CATEGORIES, nullable=True)},  -- NULL = not sorted yet
    kind         TEXT {_check('kind', FILE_KINDS, nullable=True)},
    zone         TEXT {_check('zone', ZONES, nullable=True)},
    supplier_id  INTEGER REFERENCES suppliers(id),
    filename     TEXT NOT NULL,
    path         TEXT NOT NULL,
    content_type TEXT,
    source       TEXT NOT NULL DEFAULT 'upload' {_check('source', ['upload', 'supplier_reply', 'sample'])},
    sorted_by    TEXT,
    sha256       TEXT,                   -- fingerprint at upload; files are never changed afterwards
    uploaded_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS certificates (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ingredient_id     INTEGER NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
    issuer            TEXT NOT NULL,
    cert_number       TEXT,
    expiry_date       TEXT,              -- NULL for source documents
    issuer_recognised INTEGER,           -- 1, 0, or NULL when not checked
    legible           INTEGER NOT NULL DEFAULT 1,  -- 0 = the scan could not be read; status 'unclear'
    file_id           INTEGER REFERENCES files(id),
    holder            TEXT,              -- company name on the certificate
    products          TEXT,              -- JSON: products the certificate covers
    checks            TEXT,              -- JSON list: what was checked (key, label, ok, detail, box)
    created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    doc_type    TEXT NOT NULL,           -- halal_policy, ingredient_control, traceability, ...
    title       TEXT NOT NULL,
    version     INTEGER NOT NULL DEFAULT 1,
    body        TEXT,                    -- Markdown
    status      TEXT NOT NULL DEFAULT 'draft'
                {_check('status', ['draft', 'pending_approval', 'approved', 'rejected'])},
    written_by  TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE (business_id, doc_type)
);

CREATE TABLE IF NOT EXISTS site_findings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id   INTEGER NOT NULL REFERENCES businesses(id),
    run_id        INTEGER REFERENCES runs(id),
    zone          TEXT NOT NULL {_check('zone', ZONES)},
    severity      TEXT NOT NULL {_check('severity', ['ok', 'attention', 'problem'])},
    title         TEXT NOT NULL,
    detail        TEXT,
    question      TEXT,                  -- something the owner must answer (records a photo cannot show)
    answer        TEXT,                  -- the owner's answer
    photo_file_id INTEGER REFERENCES files(id),
    checks        TEXT,                  -- JSON list: the zone checklist (label, ok, detail, box)
    suggestion    TEXT,                  -- what the owner can do about it
    status        TEXT NOT NULL DEFAULT 'open' {_check('status', ['open', 'resolved'])},
    created_at    TEXT NOT NULL,
    resolved_at   TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id  INTEGER NOT NULL REFERENCES businesses(id),
    run_id       INTEGER REFERENCES runs(id),
    from_agent   TEXT NOT NULL,
    assignee     TEXT NOT NULL {_check('assignee', AGENTS)},
    title        TEXT NOT NULL,
    detail       TEXT,
    payload      TEXT,                   -- JSON
    ref          TEXT,                   -- de-duplication key for backend triggers
    status       TEXT NOT NULL DEFAULT 'open' {_check('status', ['open', 'in_progress', 'done'])},
    result       TEXT,
    created_at   TEXT NOT NULL,
    picked_up_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS approvals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id   INTEGER NOT NULL REFERENCES businesses(id),
    run_id        INTEGER REFERENCES runs(id),
    kind          TEXT NOT NULL {_check('kind', ['message', 'document', 'question', 'plan'])},
    requested_by  TEXT NOT NULL,
    title         TEXT NOT NULL,
    supplier_id   INTEGER REFERENCES suppliers(id),
    ingredient_id INTEGER REFERENCES ingredients(id),
    document_id   INTEGER REFERENCES documents(id),
    file_id       INTEGER REFERENCES files(id),   -- question: the file it is about
    payload       TEXT,                  -- plan: JSON list of the tasks it will start
    body_ms       TEXT,
    body_en       TEXT,
    status        TEXT NOT NULL DEFAULT 'pending'
                  {_check('status', ['pending', 'approved', 'rejected', 'sent', 'failed', 'replied'])},
    comment       TEXT,
    channel       TEXT {_check('channel', ['whatsapp', 'telegram', 'email', 'manual'], nullable=True)},
    recipient     TEXT,                  -- phone or Telegram chat id the message went to
    external_id   TEXT,                  -- Twilio SID or Telegram message id
    send_error    TEXT,
    created_at    TEXT NOT NULL,
    decided_at    TEXT,
    sent_at       TEXT,
    fallback_at   TEXT,
    reply_text    TEXT,
    reply_file_id INTEGER REFERENCES files(id),
    replied_at    TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    run_id      INTEGER REFERENCES runs(id),
    agent       TEXT NOT NULL {_check('agent', ACTORS)},
    label       TEXT NOT NULL,
    message     TEXT,                    -- what the agent says to the agent it hands to / answers (speech bubble)
    status      TEXT NOT NULL {_check('status', EVENT_STATUSES)},
    handed_to   TEXT {_check('handed_to', AGENTS, nullable=True)},
    task_id     INTEGER REFERENCES tasks(id),
    approval_id INTEGER REFERENCES approvals(id),
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS packs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id  INTEGER NOT NULL REFERENCES businesses(id),
    path         TEXT NOT NULL,
    items_total  INTEGER NOT NULL,
    items_ready  INTEGER NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_business ON events(business_id, id);
CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks(assignee, status);
CREATE INDEX IF NOT EXISTS idx_certs_ingredient ON certificates(ingredient_id, id);
"""
