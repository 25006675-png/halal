# HalalReady demo runbook

The sample case and what a correct run produces: `sample_case/ANSWER_KEY.md`.

## Before you go on stage

1. `.env` has `BACKEND_URL=http://localhost:8010` (port 8000 is used by the WorkBuddy copy) and
   `GEMINI_API_KEYS=key1,key2,key3`. For the live supplier reply also set `MESSAGING_CHANNEL=telegram`,
   `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` and `TELEGRAM_FALLBACK_CHAT_ID`.
2. Three terminals:
   ```
   .venv\Scripts\python -m uvicorn backend.app:app --port 8010      # backend + dashboard
   .venv\Scripts\python -m agents.runner                             # the seven agents
   .venv\Scripts\python scripts/tunnel.py                            # only for the live Telegram reply
   ```
3. Open http://localhost:8010/app/. On the supplier phone, send `/start` to the bot. Then in Records ▸
   Suppliers (or `PATCH /suppliers/{id}`), give Minyak Murni Sdn Bhd that chat id.
4. Warm the file-reading cache once, so every file reads the same way on stage:
   `scripts/demo.py verify --runs 1` (about 15 minutes on one key, faster with three).
5. Demo ▸ **Reset the demo**.

## On stage (about 4 minutes)

| Step | You do | The audience sees |
|---|---|---|
| 1 | Demo ▸ **Drop the sample pile** | 15 files land in the pile |
| 2 | **Start** (Mak Teh's one instruction) | Coordinator sorts the trays and hands work to three agents at once |
| 3 | Wait 2–4 min, narrate the Conversation | Checker → Chaser (oil has no certificate); Checker asks Mak Teh for a clearer ikan bilis copy; Inspector → Checker (Cap Merpati Hijau on the shelf); Auditor returns or passes documents |
| 4 | **Approve and send** the message to Minyak Murni | Message goes out on Telegram |
| 5 | The "supplier" replies with the certificate photo (`sample_case/kept_back/reply_certificate_minyak_murni.png`) | Chaser → Checker; cooking oil turns green |
| 6 | In the "Clearer copy needed" card, attach `clear_copy_certificate_hasil_laut.png` and send | Ikan bilis turns green |
| 7 | Records ▸ Pack ▸ **Assemble now** | Checklist with what is still open (the undeclared oil) |
| 8 | Optional: Demo ▸ **Jump 4 months ahead** | Renewal Watch wakes for garlic/shallot paste and sugar |

## If something goes wrong

- **Telegram reply doesn't arrive:** Demo ▸ **Supplier replies (fallback)**. Same code path as a real reply.
- **Agents are slow or Gemini fails:** `scripts/demo.py snapshot restore verify_run1` loads a recorded good
  run (after all three moments). Say it is a recorded run.
- **Dashboard looks stuck:** reload the page; it replays the conversation from the database.
- **Start over:** Demo ▸ Reset the demo.

## Checking reliability

`scripts/demo.py verify --runs 3` runs the whole scenario with the real agents and checks 30+ points of
the answer key each time. `--no-cache` re-reads every file with Gemini (the strict test).
