"""
HalalReady: one-command database reset for the demo.

Empties every table, clears uploads, resets the date and seeds the sample
business. Uses the running backend if there is one, otherwise works on the
database file directly.

    python scripts/reset_db.py
    python scripts/reset_db.py --replay     # then load the fake Prepare run instantly
"""

import argparse
import asyncio
import shutil
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", default="http://localhost:8000")
    parser.add_argument("--replay", action="store_true", help="load the fake Prepare run afterwards")
    args = parser.parse_args()

    try:
        httpx.post(f"{args.backend}/admin/reset", timeout=10).raise_for_status()
        print(f"Reset through the running backend at {args.backend}.")
    except httpx.HTTPError:
        from backend.database import UPLOAD_DIR, reset_db, init_db
        from backend.seed import seed

        async def direct():
            await init_db()
            await reset_db()
            await seed()

        asyncio.run(direct())
        shutil.rmtree(UPLOAD_DIR, ignore_errors=True)
        print("Backend not running; reset the database file directly.")

    if args.replay:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "replay_events.py"),
                        "--backend", args.backend, "--instant"], check=True)


if __name__ == "__main__":
    main()
