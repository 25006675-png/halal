# Sample case: Mak Teh Sambal (fictional), tuned for three demo moments

Everything here is fictional and every file is marked "SAMPLE - FICTIONAL". Files are drawn by
`scripts/make_sample_case.py`; real photos can replace the site pictures if they keep the same names
and show the same things.

**Demo date:** 15 Oct 2026 (`scripts/demo.py reset` sets it). **Date jump for Renewal Watch:** 15 Feb 2027.

## The three moments

| # | Moment | What the audience sees |
|---|---|---|
| 1 | **Waiting on a supplier** | Cooking oil (MURNI, Minyak Murni Sdn Bhd) has an invoice but no certificate → Checker asks Chaser → Chaser drafts a Malay/English message → owner approves → supplier replies on Telegram with the certificate → Checker reads it → oil turns green. |
| 2 | **Not sure** | The ikan bilis certificate (Hasil Laut Kuala) is an unreadable scan → Checker marks it *unclear*, guesses nothing, and asks the owner for a clearer copy → owner uploads it → ikan bilis turns green. |
| 3 | **Conflict** | The store photo shows 2 tins of **CAP MERPATI HIJAU** oil next to the declared MURNI tins → Inspector flags it and hands it to Checker → Checker confirms it is not declared and has no certificate, adds it as "found on site", and asks the owner. |

## Files

**Pile (`sample_case/pile/`, dropped all at once):**

| File | Tray | Notes |
|---|---|---|
| 01_ssm_registration | Company | |
| 02_company_profile | Company | owner Siti Rahmah binti Yusof (Mak Teh), halal supervisor Nurul Ain binti Hassan |
| 03_recipe_sambal_tumis | Products | chilli, oil, shallot paste, garlic paste, sugar |
| 04_recipe_sambal_ikan_bilis | Products | the same plus ikan bilis |
| 05_supplier_list | Suppliers | 5 suppliers with brands and phones |
| 06_certificate_cili_maju | Suppliers | dried chilli, JAKIM, valid to 31 Aug 2027 |
| 07_certificate_bawang_segar | Suppliers | shallot **and** garlic paste on one certificate, JAKIM, valid to 28 Feb 2027 |
| 08_certificate_hasil_laut | Suppliers | **unreadable scan** (moment 2) |
| 09_certificate_gula_manis | Suppliers | sugar, JAKIM, valid to 31 Mar 2027 |
| 10_invoice_minyak_murni | Suppliers | MURNI oil invoice, "halal certificate available on request" (moment 1) |
| 11_photo_store | Site, store | MURNI tins plus **2 CAP MERPATI HIJAU tins** (moment 3) |
| 12–15_photo_* | Site | processing, packing, cleaning (chemicals in a closed cabinet), waste (lids closed): nothing to flag |

**Kept back (`sample_case/kept_back/`):**
- `reply_certificate_minyak_murni.png`: sent from the "supplier" phone as the live reply (JAKIM, valid to 30 Jun 2027).
- `clear_copy_certificate_hasil_laut.png`: uploaded by the owner as the clearer copy (JAIS, valid to 30 Sep 2027).

## What a correct run produces (checked by `scripts/demo.py verify`)

After the first pass:
- All 15 files sorted; the invoice under Suppliers; each photo in its zone.
- 6 declared ingredients with brands: dried chilli, cooking oil, shallot paste, garlic paste, ikan bilis, sugar.
- Cooking oil **missing**, one message to Minyak Murni waiting for approval (Malay and English).
- Ikan bilis **unclear**, no number or date recorded, a "clearer copy" question for the owner, no supplier message.
- Store zone **issue** (Cap Merpati Hijau), Inspector → Checker handoff, a found-on-site ingredient with no
  certificate, and a question for the owner.
- No false alarms: the other 4 ingredients valid, the other 4 zones clear, only Minyak Murni messaged.
- Halal policy, ingredient control and traceability passed the Auditor and wait for approval.
- The Coordinator's status sentence on the Today tab.

After the oil reply: cooking oil **valid**. After the clear copy: ikan bilis **valid**.

**Renewal Watch** (jump to 15 Feb 2027): garlic and shallot paste (one certificate, 13 days) → one renewal
task; sugar (44 days) → one renewal task. Dried chilli and the oil stay valid.
