"""
HalalReady backend: seed the fictional sample business.

Only the business itself is seeded. Ingredients, suppliers, certificates and
documents come from the agents (or from scripts/replay_events.py), so the
Prepare run starts from the owner's pile, as in the demo.
"""

import os

from .database import connect, fetch_one, insert


async def seed():
    async with connect() as db:
        if await fetch_one(db, "SELECT id FROM businesses LIMIT 1"):
            return
        await insert(db, "businesses", {
            "id": 1,
            "name": "Mak Teh Sambal Sdn Bhd (sample, fictional)",
            "owner_name": "Mak Teh",
            "owner_phone": os.getenv("DEMO_OWNER_PHONE") or None,
            "owner_telegram_chat_id": os.getenv("TELEGRAM_OWNER_CHAT_ID") or None,
            "is_sample": 1,
        })
