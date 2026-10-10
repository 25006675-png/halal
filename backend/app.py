"""
HalalReady backend: FastAPI application.

Run from the repo root:
    python -m uvicorn backend.app:app --reload --port 8000

Routes:
    routes_agent.py      /agent/*     tools the MCP connector calls
    routes_dashboard.py  everything the dashboard calls, plus owner actions
    routes_webhooks.py   /webhooks/*  supplier replies through the tunnel
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import messaging
from .database import ROOT, connect, fetch_all, init_db
from .routes_agent import router as agent_router
from .routes_dashboard import router as dashboard_router, send_fallback
from .routes_demo import router as demo_router
from .routes_webhooks import router as webhook_router
from .seed import seed

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("backend")


async def fallback_loop():
    """Every minute: re-send on Telegram any WhatsApp message still unanswered after the limit."""
    while True:
        await asyncio.sleep(60)
        try:
            async with connect() as db:
                rows = await fetch_all(db, "SELECT * FROM approvals WHERE status = 'sent' AND channel = 'whatsapp' "
                                           "AND fallback_at IS NULL")
                for a in rows:
                    if messaging.fallback_due(a):
                        log.info("Falling back to Telegram for approval %s", a["id"])
                        await send_fallback(db, a)
        except Exception:
            log.exception("Fallback check failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await seed()
    task = asyncio.create_task(fallback_loop())
    log.info("Messaging: %s", messaging.status())
    yield
    task.cancel()


app = FastAPI(title="HalalReady backend", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def tunnel_guard(request: Request, call_next):
    """
    Through the ngrok tunnel, only the webhooks are reachable, so the public
    URL can't approve messages or reset the database. Set ALLOW_REMOTE=1 for a
    joint session where teammates use the whole API over the tunnel.
    """
    via_tunnel = "x-forwarded-for" in request.headers or "ngrok-trace-id" in request.headers
    open_paths = ("/webhooks/", "/health")
    if via_tunnel and os.getenv("ALLOW_REMOTE") != "1" and not request.url.path.startswith(open_paths):
        return JSONResponse({"detail": "Only webhooks are reachable through the tunnel"}, status_code=403)
    return await call_next(request)


app.include_router(agent_router)
app.include_router(dashboard_router)
app.include_router(webhook_router)
app.include_router(demo_router)

# The owner's dashboard: http://localhost:<port>/app/
app.mount("/app", StaticFiles(directory=ROOT / "dashboard", html=True), name="dashboard")


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse("/app/")
