"""
Gemini client with a pool of API keys.

Keys come from GEMINI_API_KEYS (comma separated) or gemini_key / GEMINI_API_KEY.
Each request takes the next key that still has room in its per-minute budget
(GEMINI_RPM_PER_KEY, default 12, under the free tier's limit), so requests are
paced instead of refused. A key that is refused anyway rests for a while and
the request moves to another key: three free-tier keys behave like one bigger
quota.
"""

import asyncio
import itertools
import logging
import re
from collections import deque
import os
import time

from google import genai
from google.genai import errors, types

log = logging.getLogger("gemini")

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
RPM_PER_KEY = int(os.getenv("GEMINI_RPM_PER_KEY", "12"))


KEY_NAME = re.compile(r"^(gemini_api_keys?|gemini_key)\d*$", re.I)


def _keys() -> list[str]:
    """Every key in the environment: GEMINI_API_KEYS=a,b,c and/or gemini_key, gemini_key2, gemini_key3, ..."""
    names = sorted((n for n in os.environ if KEY_NAME.match(n)),
                   key=lambda n: (re.sub(r"\d+$", "", n.lower()), int(re.search(r"(\d*)$", n).group(1) or 0)))
    raw = ",".join(os.environ[n] for n in names)
    keys = list(dict.fromkeys(k.strip().strip("'\"") for k in raw.split(",") if k.strip()))  # no duplicates
    if not keys:
        raise RuntimeError("No Gemini key. Set gemini_key=... (and gemini_key2, gemini_key3, ...) in .env")
    return keys


class KeyPool:
    def __init__(self):
        self.clients = [genai.Client(api_key=k) for k in _keys()]
        self.resting_until = [0.0] * len(self.clients)
        self.recent = [deque() for _ in self.clients]   # request times in the last minute, per key
        self.sent = 0                                     # requests sent to Gemini, to measure a run
        self._order = itertools.cycle(range(len(self.clients)))

    @property
    def size(self) -> int:
        return len(self.clients)

    def _next(self) -> tuple[int | None, float]:
        """A key with room now, or None and how long until one has room."""
        now = time.monotonic()
        soonest = float("inf")
        for _ in range(len(self.clients)):
            i = next(self._order)
            window = self.recent[i]
            while window and now - window[0] >= 60:
                window.popleft()
            if self.resting_until[i] > now:
                soonest = min(soonest, self.resting_until[i] - now)
            elif len(window) >= RPM_PER_KEY:
                soonest = min(soonest, 60 - (now - window[0]))
            else:
                window.append(now)
                return i, 0.0
        return None, soonest

    async def generate(self, contents, config: types.GenerateContentConfig, model: str = MODEL,
                       attempts: int = 6) -> types.GenerateContentResponse:
        last_exc: Exception | None = None
        attempt = 0
        while attempt < attempts:
            i, wait = self._next()
            if i is None:
                if wait > 600:
                    raise RuntimeError("Every Gemini key has used its free daily quota. Add another key "
                                       "(GEMINI_API_KEYS) or wait for the quota to reset.")
                await asyncio.sleep(max(0.2, wait) + 0.05)
                continue
            attempt += 1
            self.sent += 1
            try:
                return await asyncio.wait_for(
                    self.clients[i].aio.models.generate_content(model=model, contents=contents, config=config),
                    timeout=120)
            except errors.APIError as exc:
                last_exc = exc
                if exc.code == 429 and "PerDay" in str(exc):
                    # The free tier's daily request limit: this key is done until the quota resets.
                    self.resting_until[i] = time.monotonic() + 6 * 3600
                    attempt -= 1
                    log.error("Key %d used up its daily quota for %s; leaving it out", i + 1, model)
                elif exc.code == 429:
                    self.resting_until[i] = time.monotonic() + 30
                    log.warning("Key %d rate-limited; resting it 30s", i + 1)
                elif exc.code in (500, 502, 503, 504):
                    await asyncio.sleep(2 * (attempt + 1))
                else:
                    raise
            except asyncio.TimeoutError as exc:
                last_exc = exc
                log.warning("Gemini call timed out (key %d)", i + 1)
        raise RuntimeError(f"Gemini failed after {attempts} attempts: {last_exc}")


_pool: KeyPool | None = None


def pool() -> KeyPool:
    global _pool
    if _pool is None:
        _pool = KeyPool()
    return _pool
