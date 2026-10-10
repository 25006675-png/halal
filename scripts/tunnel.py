"""
HalalReady: public tunnel for incoming supplier replies.

Starts ngrok in front of the backend, then:
  1. tells the backend its public URL (used to check Twilio signatures)
  2. points the Telegram bot's webhook at it (if TELEGRAM_BOT_TOKEN is set)
  3. prints the Twilio WhatsApp webhook URL to paste into the Twilio console

Only /webhooks/* and /health answer through the tunnel; everything else is
refused unless ALLOW_REMOTE=1 (see backend/app.py).

    python scripts/tunnel.py                 # start ngrok and keep it running (Ctrl+C to stop)
    python scripts/tunnel.py --use-running   # ngrok is already running; just register the URL

One-time ngrok setup: ngrok config add-authtoken <token from dashboard.ngrok.com>
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

NGROK_API = "http://127.0.0.1:4040/api/tunnels"


def public_url(timeout: float = 20) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            tunnels = httpx.get(NGROK_API, timeout=2).json().get("tunnels", [])
            for t in tunnels:
                if t.get("public_url", "").startswith("https://"):
                    return t["public_url"]
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    sys.exit("ngrok did not report a public URL. Is your authtoken set? (ngrok config add-authtoken ...)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8000, help="backend port (default 8000)")
    parser.add_argument("--use-running", action="store_true", help="use an ngrok that is already running")
    args = parser.parse_args()
    backend = f"http://localhost:{args.port}"

    proc = None
    if not args.use_running:
        ngrok = shutil.which("ngrok")
        if not ngrok:
            sys.exit("ngrok not found. Install it from https://ngrok.com/download")
        proc = subprocess.Popen([ngrok, "http", str(args.port), "--log", "stdout"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    url = public_url()
    print(f"Public URL: {url}")

    try:
        httpx.put(f"{backend}/messaging/public-url", json={"url": url}, timeout=5).raise_for_status()
        print(f"Backend at {backend} now knows its public URL.")
    except httpx.HTTPError as exc:
        print(f"WARNING: could not reach the backend at {backend} ({exc}). Start it, then run with --use-running.")

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if token:
        body = {"url": f"{url}/webhooks/telegram", "allowed_updates": ["message", "edited_message"]}
        if os.getenv("TELEGRAM_WEBHOOK_SECRET"):
            body["secret_token"] = os.environ["TELEGRAM_WEBHOOK_SECRET"]
        resp = httpx.post(f"https://api.telegram.org/bot{token}/setWebhook", json=body, timeout=10).json()
        print(f"Telegram webhook: {'set' if resp.get('ok') else 'FAILED: ' + str(resp.get('description'))}")
    else:
        print("Telegram webhook: skipped (TELEGRAM_BOT_TOKEN not set)")

    print(f"""
Twilio WhatsApp: in the Twilio console, open Messaging > Try it out > Send a WhatsApp message >
Sandbox settings, and set "When a message comes in" to
    {url}/webhooks/twilio    (method POST)
The ngrok URL changes every time ngrok restarts, so redo this after a restart
(or use a reserved ngrok domain).
""")

    if proc:
        print("Tunnel running. Ctrl+C to stop.")
        try:
            proc.wait()
        except KeyboardInterrupt:
            proc.terminate()


if __name__ == "__main__":
    main()
