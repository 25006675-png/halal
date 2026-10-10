# HalalReady — Project Proposal

*AI Hackerdorm Dormathon 2026 · Track 2 (Tencent WorkBuddy) · Updated 10 Oct 2026*

> This version replaces the earlier technical plan, `CONTRACT.md` and UI draft, which still describe the four-agent version (Coordinator, Paper, Place, Upkeep).

---

## 1. Summary

HalalReady is a team of AI agents that helps a small Malaysian food manufacturer prepare for halal certification and stay compliant afterwards, without paying a consultant. The owner drops in her paperwork and site photos; six agents check certificates, chase suppliers, draft the required documents, check the premises, and assemble an application pack. The owner approves every outgoing message, and the app never declares anything halal.

**One-line pitch:** *WorkBuddy is the engine; HalalReady is the halal team built on it, with the rules, the records and the follow-up a small factory owner can't manage alone.*

---

## 2. Problem

- Halal certification is often required to sell into supermarkets, but small manufacturers struggle with the paperwork.
- JAKIM received 15,605 halal applications in 2023 and 14,707 by September 2024.
- A study of Johor food SMEs named **documentation and cost** as the main challenges.
- 3,068 certifications had been revoked for non-compliance as of late 2024, so staying compliant matters as much as getting certified.
- Consultancy for micro firms can cost **up to RM10,000** (one consultant quoted in the press).
- Supplier certificates expire and certification bodies change: JAKIM recognises 96 foreign certification bodies (August 2026) and withdrew three in 2025.

## 3. User

The owner or halal supervisor of a small food factory that is already operating.

**Demo persona:** Mak Teh (fictional), a sambal maker who needs the halal logo to get into a supermarket. Her paperwork is a pile.

## 4. Scope and principles

- **One tailored demo story** on one fixed, fictional sample case — not a general system.
- **Three pillars:** Paper (fully built), Place (on-site self-check across the whole premises), Upkeep (renewals and changes over time).
- **Knowledge base:** summarised rule files and short reference notes from official sources, each with a source pointer. No RAG.
- **Hard rules:**
  - The app never declares anything halal; it flags *possible issues* for the owner to check.
  - Nothing is sent without the owner's approval.
  - All sample data is fictional and labelled as such.
  - The app prepares the pack; the owner submits it to JAKIM herself.

---

## 5. Agents

| Agent | Job |
|---|---|
| **Coordinator** | Sorts uploaded files into the four input trays, assigns work, resolves conflicts between agents, keeps the readiness score, writes the owner's status sentence, assembles the application pack |
| **Certificate Checker** | Lists ingredients and suppliers; checks each certificate's expiry and issuer against JAKIM's recognised list |
| **Supplier Chaser** | Drafts supplier messages (Malay and English), sends them after owner approval, files replies |
| **Document Writer** | Drafts the halal policy, ingredient control and traceability procedures for owner review |
| **On-site Inspector** | Pre-audit self-check of the whole premises from photos of each zone; flags undeclared brands and visible issues; asks for records a photo can't show |
| **Renewal Watch** | Watches expiry dates; starts renewal requests early and alerts the owner |

### Handoffs

| From → To | What is handed over |
|---|---|
| Coordinator → all | Sorted files and first tasks |
| Certificate Checker → Supplier Chaser | Expired or missing certificates |
| Certificate Checker → Document Writer | Confirmed ingredient and supplier list |
| Certificate Checker → On-site Inspector | Declared brand list |
| Supplier Chaser → Certificate Checker | New certificate from a supplier reply |
| On-site Inspector → Certificate Checker | Unknown brand found on site |
| On-site Inspector → Document Writer | Zone details for the procedures |
| Renewal Watch → Supplier Chaser + owner | Upcoming expiry |
| All → Coordinator | Status updates for the readiness score |

### Flow

1. Coordinator sorts the pile.
2. Certificate Checker, Document Writer and On-site Inspector start together.
3. Handoffs as above; the owner approves outgoing messages.
4. Coordinator assembles the application pack.
5. After certification, agents go quiet and wake only on triggers: a date (expiry approaching), a reply (supplier sends a certificate), a change (new product or supplier), or a routine (periodic site photos).

### On-site Inspector: what it checks

Criteria must be confirmed against JAKIM's procedures manual (MPPHM) and MS 1500:2019 before the instructions are written.

- **From photos (five demo zones: store, processing, packing, cleaning area, waste):** brands on shelves vs the declared list; separation of non-halal or unknown items; cleanliness; pest control signs; no animals; cleaning materials away from food; covered waste.
- **Asks the owner instead of guessing:** pest control records, cleaning logs, delivery vehicles, staffing, past non-halal use of equipment.

---

## 6. Architecture

- **Agents:** WorkBuddy experts, one set of instructions per role (Expert Team if supported).
- **Connector:** one custom MCP server registered in WorkBuddy's Connectors, shared by all agents.
- **Orchestration:** a task board in the backend. Agents hand work to each other with `create_task`, pick it up with `get_my_tasks`, and close it with `complete_task`. Every handoff posts an event, so the dashboard graph is drawn from real data.
- **Backend:** FastAPI + SQLite. Does all date, status and score calculations.
- **Messaging:** Twilio WhatsApp for suppliers, Telegram as fallback after a two-hour limit. Incoming replies need a tunnel (ngrok).
- **Runs on one laptop** (WorkBuddy desktop app reaching the connector on localhost — to be confirmed).

### Connector tools (first set)

`post_event`, `create_task`, `get_my_tasks`, `complete_task`, `get_files`, `get_certificates`, `save_ingredients`, `save_document`, `save_site_finding`, `request_approval`

### Data

Tables: `files` (with `category`), `ingredients`, `suppliers`, `certificates`, `documents`, `site_findings`, `tasks`, `events` (with `handed_to`), `approvals`.

### Running modes

- **Prepare:** first run on the pile, ending in the application pack.
- **Upkeep:** event-driven; mostly idle. A "today" override lets the demo jump forward in time.

---

## 7. Dashboard

Light, minimal, human-made feel: warm paper-white background, sambal-red brand accent used sparingly, green / amber / red only for status, real document thumbnails, sentences instead of charts. Original logo (leaf + tick), never resembling JAKIM's halal logo.

| Tab | Contents |
|---|---|
| **Today** | Coordinator's status sentence ("62% ready. Two suppliers still owe certificates; I've asked them both."), journey line (Upload → Check → Fix → Documents → Pack), four input trays (Company, Products, Suppliers, Site), next renewal |
| **Agents** | Agent graph with live statuses and moving handoffs (only the active line coloured); owner feed on the right: *Needs you* (approval cards), *Working on*, *Done*. Clicking an agent shows its recent steps |
| **Records** | Binder with tabs: Ingredients, Suppliers, Documents, Site, Pack. Pack is a cover-sheet checklist with one download button |

Inputs: separate trays per category, but dropping everything at once also works — the Coordinator sorts it.

---

## 8. Demo (about four minutes, to be fitted to the official pitch length)

1. **Problem (20 s):** Mak Teh, her paperwork pile, consultants up to RM10,000.
2. **Drop the pile:** files sort into the trays; three agents start together.
3. **Red dots appear:** expired chilli paste certificate, missing cooking oil certificate; documents start filling in.
4. **Live moment:** approve the supplier message ("This card is all Mak Teh needs to see"); a phone receives it and replies with a certificate — ideally a judge presses send. Red turns green.
5. **On-site Inspector (30–40 s):** zones turn green on a floor plan; the store photo reveals a cheaper, undeclared oil brand, handed to the Certificate Checker.
6. **Renewal Watch:** jump the date four months; renewal request and phone alert. "For most of the year it's quiet; it only wakes up when something needs doing."
7. **Close:** Coordinator assembles the pack, final readiness score, cost comparison.

**Honesty and safety nets:** the main run is a sped-up replay of a real run, stated as such; the supplier reply is live. Bring a mobile hotspot, a one-command database reset, a full screen recording, Telegram as message fallback, and one unused certificate for judges' questions. Briefly show WorkBuddy running the agents so the Track 2 requirement is visible.

---

## 9. Team roles

**Person 1: Dashboard (`dashboard/`)**
- Build the three tabs: Today, Agents, Records
- Today: status sentence, journey line, four input trays that fill as the Coordinator sorts files
- Agents: graph with live steps and moving handoffs, plus the owner feed
- Records: binder with Ingredients, Suppliers, Documents, Site and Pack
- Build against the fake event replay first, then switch to the live stream
- Add replay mode and the date control

**Person 2: Backend and connections (`backend/`, `connector/`)**
- Create the database tables, including tasks, documents, site findings and `handed_to` on events
- Build `post_event` and the live stream first, plus a fake event replay script
- Build the connector with `post_event` and the task-board tools
- Register the connector in WorkBuddy and test two agents handing off a task
- Build the remaining endpoints and tools
- Write the calculations: days to expiry, certificate status, readiness score, with a "today" override
- Build pack assembly from approved items, marking anything missing
- Add Twilio WhatsApp with Telegram fallback
- Set up the tunnel for incoming replies

**Person 3: Agents and content (`agents/`, `rules/`, `sample_case/`)**
- Write the knowledge base from official sources, with a source pointer on every rule, including site checks per zone
- Create the sample case: fictional invoices, certificates, recipes and photos of five zones
- Write instructions for the six agents
- Write message templates in Malay and English
- Run the full case repeatedly and tighten instructions until results repeat
- Record a backup run of the demo

**Collaboration:** one GitHub repo; `CONTRACT.md` defines events, tasks and API; everyone runs locally; ngrok only for joint sessions; full agent runs mostly by Person 3 to save WorkBuddy credits; the integration laptop is the demo laptop.

**First milestone:** two agents (Certificate Checker → Supplier Chaser) hand off a task through the connector, visible on the events page.

---

## 10. Differentiation

| Plain WorkBuddy chat | HalalReady |
|---|---|
| Owner must know what to ask | Agents know the halal process |
| General knowledge | Rules from official sources, recognised-bodies list |
| Model-estimated dates | Backend-calculated expiry and score |
| Forgets between chats | Stored records for a year of upkeep |
| Text only | Real WhatsApp messages after approval |
| One long conversation | Six specialised agents with handoffs |
| Chat box | To-do list and one-tap approvals |

Competitors found: WhatsHalal, Halal Personal Advisor. HalalSuite not yet checked.

---

## 11. Open questions

**For the organisers (ask today, in writing):**
- Can other coding assistants (e.g. Claude Code) be used for backend code if the agents run on WorkBuddy?
- Rules on pre-built work, pitch length and judging criteria.

**For WorkBuddy (test today):**
- Custom MCP connector on localhost; separate experts / Expert Teams; parallel runs; image input; starting runs from the dashboard.

**For halal content:**
- What JAKIM requires in internal documents for small businesses (for the Document Writer).
- Site requirements per zone from MPPHM and MS 1500:2019 (for the On-site Inspector).
- Real section order of the MYeHALAL application form (for the pack).
- How supplier changes between renewals are reported to JAKIM.
- Most rules so far come from third-party guides; replace with JAKIM's own sources.

## 12. Next actions

1. Send the organisers the rules questions.
2. Run the two-agent connector test in WorkBuddy.
3. Update `CONTRACT.md`, the technical plan and the UI draft to this version.
4. Person 3 starts the knowledge base and sample files from official sources.
