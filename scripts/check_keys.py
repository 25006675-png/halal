r"""
Check every Gemini key in .env with one tiny request each.

    .venv\Scripts\python scripts/check_keys.py

Prints OK, out of daily quota, rate-limited or invalid for each key (never the
key itself). Keys from the same Google Cloud project share one quota, so make
each key in a new project.
"""

import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from google import genai  # noqa: E402
from google.genai import errors  # noqa: E402

from agents.gemini import MODEL, _keys  # noqa: E402


def main():
    keys = _keys()
    print(f"{len(keys)} key(s) in .env, model {MODEL}")
    ok = 0
    for n, key in enumerate(keys, 1):
        t = time.time()
        try:
            client = genai.Client(api_key=key)   # kept in a variable: a temporary client closes too early
            client.models.generate_content(model=MODEL, contents="Reply with OK")
            print(f"  key {n} (…{key[-4:]}): OK ({time.time() - t:.1f}s)")
            ok += 1
        except errors.APIError as exc:
            text = str(exc)
            why = ("out of daily quota" if "PerDay" in text else "rate-limited, try again in a minute" if exc.code == 429
                   else "invalid key" if exc.code in (400, 401, 403) else f"error {exc.code}")
            print(f"  key {n} (…{key[-4:]}): {why}")
    print(f"{ok} of {len(keys)} ready: about {ok * 12} requests a minute, {ok * 500} a day.")


if __name__ == "__main__":
    main()
