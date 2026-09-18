# SkyAssist — Customer-Facing Resolution Agent

**Assignment 3 · Agentic AI Factory (AIONOS) · airline disruption journey**

SkyAssist handles passengers hit by flight disruptions on **Wednesday, 23 September 2026** —
a cancelled Delhi–Goa flight, a 4-hour Mumbai–Bengaluru delay, and a 6-hour Delhi–Hyderabad
delay. It works out what the customer wants, asks only what it genuinely needs to know,
executes the correct action when it has the authority, escalates when it does not, keeps its
composure with angry customers, and leaves a complete, replayable record of everything it did
and why.

---

## Live demo

**→ `https://customer-facing-resolution-agent.onrender.com/`** *(replace with your URL after deploying)*

> **Two things to know before you click.**
> **(1)** This runs on Render's free tier, which sleeps after 15 minutes of inactivity — the
> **first request takes about a minute** while the container wakes. Everything after that is
> fast.
> **(2)** Free instances cannot have a persistent disk, so the audit trail is **per visit**:
> it fills up completely as you use the app and resets when the instance restarts. That is a
> hosting constraint, not a design choice — see [Known limitations](#known-limitations).

No login. Pick a customer on the left, click a demo scenario, watch the right-hand panel.

---

## The one design rule

> **The LLM talks. The code decides.**

No compensation amount, fare waiver, refund or rebooking is ever decided by the language
model. Every rupee comes from [`backend/policy/engine.py`](backend/policy/engine.py) — plain,
unit-tested Python with no model in the loop. The LLM does exactly two jobs: classify the
customer's intent and sentiment, and phrase decisions the engine already made.

This is enforced structurally, not by prompting:

- Every customer-facing message is generated **downstream of the authority gate**. Even the
  clarifying questions come from an engine verdict, so there is no path to a reply that
  bypassed policy.
- `_verdict()` in the engine rejects any action outside the data pack's allowed list, and
  only an `execute` verdict may carry actions at all.
- Everything the model returns is **sanitised before it reaches the engine** — unknown action
  types dropped, numbers coerced, flags forced to booleans.

So the natural examiner question — *"what if the model hallucinates a free upgrade?"* — has a
structural answer: it cannot. The model only phrases outcomes; an unauthorised action fails
the gate and never reaches the ledger.

---

## The three scored scenarios

These are the acceptance tests. Each is a one-click preset in the UI.

| # | Customer | Situation | What the agent must do |
|---|---|---|---|
| 1 | **Priya Nair** · Gold · SK4821X | SK-204 Delhi→Goa **cancelled**; she is furious and wants a full cash refund **plus a free business-class upgrade** | Refund **executed** (full, 7 business days, original payment method). Upgrade **declined** — beyond stated policy. Gold gives priority rebooking, never extra compensation. |
| 2 | **Arvind Kulkarni** · Silver · TR1190B | SK-118 Mumbai→Bengaluru **delayed 4h**; frustrated about a missed meeting, asks for a hotel | ₹500 meal voucher + lounge access **executed**. Hotel **declined** — it applies only above 5 hours. No compensation for the missed meeting (consequential loss isn't in the policy). |
| 3 | **Meher Kaur** · Platinum · WL7742 | SK-305 Delhi→Hyderabad **delayed 6h**; wants a **full night's hotel** and a **higher-fare flight** (₹2,000 difference) | Voucher + lounge + hotel **for the 6 delayed hours executed**. Full night **declined**. ₹2,000 waiver **escalated** — above the agent's ₹1,500 limit. All three verdict types in one turn. |

**The traps.** Scenario 2 is the one a human — or an LLM — gets wrong: four hours *feels* long
enough for a hotel. Only the deterministic engine holds the line at five. Scenario 3 contains
two different over-reaches that must be handled two different ways: one declined, one
escalated. And in Scenario 1, "making it right" with a free upgrade is a failure, not
generosity.

Worth also trying: a **legal threat** ("I'm speaking to my lawyer") → immediate escalation as
a high-priority ticket, no negotiation. A **refund to a different card** → prohibited,
escalated. A bare **"my flight got cancelled"** → the agent asks exactly one question, and
stops asking after two.

---

## Architecture

Five layers, one deployable service. Full detail in **[ARCHITECTURE.md](ARCHITECTURE.md)**.

| Layer | What it is | Responsibility |
|---|---|---|
| Client | React 18 (JSX), esbuild | Three-pane desk: customers, conversation, action record. Light/dark. |
| API | FastAPI + SSE | `POST /api/chat` streams the turn; REST reads for the audit trail. Also serves the built frontend. |
| Agent | LangGraph state machine | 8 nodes. Routes every reply through the authority gate. |
| **Decisions** | **Pure Python policy engine** | **The 6 service rules + the authority gate. No LLM.** |
| Records | SQLite, append-only | Turns, actions and escalation tickets, each citing its rule. |

### Conversation flow

```
identify → understand → facts → decide → { clarify | escalate | respond } → record
```

1. **identify** — resolve the customer and their disrupted booking. Pure lookup.
2. **understand** — LLM returns strict JSON: intent, sentiment, requested actions, legal
   threat. Sanitised before use; a deterministic keyword check backstops the legal-threat
   detection so a model miss cannot skip a mandatory escalation.
3. **facts** — deterministic reads from the data pack.
4. **decide** — *the hinge.* Every request runs through `evaluate_request()`, producing
   per-request verdicts: `execute`, `decline`, `escalate` or `clarify`.
5. **clarify** — asks one question, built only from the options the verdict carries. Capped at
   two per conversation, counted from the ledger.
6. **escalate** — builds the handover packet **and persists it as a ticket** with a reference.
7. **respond** — the LLM phrases the verdicts. It never sees anything it isn't allowed to say.
8. **record** — append-only turn + one action row per effect, each with its authorising rule.

---

## The policy engine

Every rule in the supplied data pack is one small, testable function.

| Rule | Function | Behaviour |
|---|---|---|
| Cancellation rebooking | `entitle_cancellation()` | Airline-caused cancellation → customer's choice of free rebooking within 24h **or** a full refund. Validates the booking actually qualifies. |
| Delay compensation | `delay_compensation()` | <3h → ₹500 meal voucher · >3h → + lounge · >5h → + hotel covering **only the delayed hours**, never a full night |
| Refund processing | `evaluate_request("refund")` | Full refund in 7 business days, original payment method only |
| Fare difference | `evaluate_request("rebook")` | Agent may waive ≤ ₹1,500; above that → supervisor approval |
| Loyalty tier | `get_priority_rebooking()` | Gold/Platinum → priority rebooking. **Never** extra compensation. |
| Allowed vs prohibited | `evaluate_request()` + `_verdict()` | The single authority gate every request passes before anything executes |

### The five prohibited actions → escalation

| Prohibited | Where it fires |
|---|---|
| Compensation beyond stated policy | `evaluate_request` → `prohibited_compensation` |
| Waiving a fare difference above ₹1,500 | `rule="fare_difference"` |
| Exceptions for non-airline-caused disruptions | `prohibited_exception` |
| Threats of legal action / formal complaints | `decide` short-circuit → `prohibited_legal` (high-priority ticket) |
| Refunds to a different payment method | `rule="refund_processing"` |

**A note on the fare waiver.** Whether the airline absorbs a fare difference is decided on the
*amount*, not on how the customer phrased it. When the disruption is airline-caused, asking to
be moved to a higher-fare flight is implicitly asking us to absorb the difference — so it runs
through the agent's waiver authority either way. Scenario 3 therefore escalates on ₹2,000 >
₹1,500 alone, never on a model's guess about intent.

---

## Grounding: only the supplied data

- **The data pack is the only source of fact.** Customers, bookings, statuses, delay hours and
  tiers live in [`backend/data/datapack.json`](backend/data/datapack.json), transcribed from
  the brief. Out-of-pack questions get an honest "I don't have that information."
- **No flight schedules or fares were supplied, so none are invented.** The agent says "the
  next available flight within 24 hours" — the rule's own wording — and never names a
  replacement flight number, time or seat. `loader.py` deliberately exposes no schedule
  accessor, so nothing downstream can reach for one. A test asserts this stays true.
- **Fare differences are customer-stated and unverified.** Nothing in the pack prices a flight,
  so the ₹2,000 in Scenario 3 can only come from the customer. It is tagged
  `fare_difference_source: "customer_stated"` on the verdict, in the ledger and in the ticket.
- **Sample conversations A/B/C are used for tone only**, exactly as the pack instructs — never
  as a source of policy or fact.
- **Tone never changes entitlements.** An angrier customer gets a better-worded answer, not a
  bigger voucher.

---

## Audit trail and structured tickets

Everything is retrievable, and every entry cites the rule that authorised it.

| Endpoint | Returns |
|---|---|
| `GET /api/sessions` | Every session handled |
| `GET /api/sessions/{id}` | Full transcript **with the verdicts that drove each turn** |
| `GET /api/actions` | The whole action ledger (or `?session_id=` for one) |
| `GET /api/tickets` | Structured escalation tickets (or `?session_id=`) |
| `GET /healthz` | Status, engine and model |

Each escalation creates a ticket (`SKY-0001`, …) carrying the conversation history, booking
facts, the rules checked, the reason, and a priority — the packet a human agent picks up.
Legal threats are raised at high priority. Rows are never updated or deleted.

In the UI, the right-hand panel shows the same record live: counts by status, filters, and
every executed / declined / escalated / clarified action with its rule.

---

## Running it locally

### Windows (PowerShell)

```powershell
.\run.ps1
```

### macOS / Linux

```bash
./run.sh
```

Either creates the virtual environment, installs dependencies, builds the frontend and serves
everything on <http://localhost:8000>. There is no separate frontend server — FastAPI serves
the built React bundle.

### Docker (closest to production)

```bash
docker build -t skyassist .
docker run --rm -p 8000:8000 skyassist          # works with no API key (mock engine)
```

### Choosing the engine

Copy `.env.example` to `.env`. The app loads it at startup
([`backend/config.py`](backend/config.py)); a shell environment variable still wins over the
file.

```ini
LLM_PROVIDER=groq        # groq | ollama | mock
GROQ_API_KEY=gsk_...
```

| Provider | Use it for |
|---|---|
| `groq` | Hosted, free tier. The demo and deployment engine. |
| `ollama` | Fully local (`ollama pull llama3.1:8b`). Zero cost, works offline. |
| `mock` | Deterministic, no network. Tests, CI, and the Docker default. |

> **Groq retires hosted models.** `llama-3.3-70b-versatile` was decommissioned and now returns
> 404. The default is `openai/gpt-oss-120b`. If you hit a 404, list what your key can actually
> reach and set `LLM_MODEL` accordingly:
> ```bash
> python -m backend.llm.provider
> ```

---

## Tests

```bash
python -m pytest backend -q          # 57 passed
```

**No LLM, key or network required** — `backend/conftest.py` forces the mock provider and a
throwaway database, so the suite never touches your real ledger.

What they cover:

- **The three scored scenarios**, asserted against the policy engine with no LLM involved.
  Fixtures are built from the real `datapack.json`, so data drift fails a test.
- **Threshold boundaries** at exactly 3h, exactly 5h and exactly ₹1,500 — the places an
  off-by-one would quietly change a payout.
- **The sanitiser** that guards the authority gate against malformed model output (string fare
  differences, unknown action types, non-dict entries).
- **Structural guarantees**: declined and escalated verdicts can never carry actions; no action
  type outside the allowed list can be emitted; the data pack contains no invented schedule.
- **End-to-end graph runs** for all three scenarios via the mock provider, plus the clarify cap,
  ticket creation, idempotency (asking twice issues one voucher), and transcript replay.

---

## Inputs, sources and assumptions

**Inputs.** The Assignment 3 Data Pack (customer profiles, booking data, six service rules,
allowed/prohibited actions, three sample conversations, three scenarios) and the Assignment
Brief. Nothing else.

**Assumptions, declared:**

- Exercise date fixed at **Wed 23 Sep 2026**; all reasoning is relative to the data pack, never
  to live flight data.
- The pack lists Arvind's PNR as `TR1190B` in his profile but `TR11390B` in the Scenario 2 text
  — **normalised to `TR1190B`** and recorded as a discrepancy.
- Delay boundaries at **exactly 3h / 5h** are treated as "not more than". The pack says "under 3
  hours" and "more than 3/5 hours", leaving the exact boundary undefined; the agent resolves it
  conservatively (3h → voucher only, 5h → no hotel). Both are unit-tested.
- **No flight schedules or fares were supplied**, so none are modelled — see
  [Grounding](#grounding-only-the-supplied-data).
- Refund and rebooking "execution" is a **ledger write in a prototype** — there is no payment or
  PSS integration.
- Customer identity comes from the picker, simulating an authenticated channel; a PNR is asked
  for only when genuinely ambiguous.

---

## AI tools used

The brief permits AI tools and requires them to be listed.

| Tool | How it was used |
|---|---|
| Claude (Anthropic), via Claude Code | Drafting the architecture, transcribing the data pack into JSON, implementing the backend and frontend, and auditing the implementation against the brief |
| Groq — `openai/gpt-oss-120b` | **Runtime LLM** for the hosted demo: intent/sentiment classification and phrasing verdicts |
| Ollama — `llama3.1:8b` | **Runtime LLM** for fully local runs |
| Deterministic mock provider | Written for this project so the test suite and CI need no model at all |

Every design decision in the policy engine was reviewed line by line against the data pack;
the three scored scenarios are its unit tests.

---

## Requirement coverage

| Brief requirement | Where it lives |
|---|---|
| Understand the customer's intent | `understand` node — intent enum + requested actions + sentiment, strict JSON, sanitised |
| Ask only necessary questions | `clarify` verdict from the engine — only when the decision branches on the customer's choice, max 2, counted in the ledger |
| Use the supplied data and policies | `datapack.json` + `policy/engine.py`; no schedule or fare data invented |
| Recommend or execute the correct next action | `decide` → authority gate → validated action execution |
| Handle an angry or confused customer | Sentiment classification → tone directives; Sample A/B/C style for tone only |
| Escalate when authority is missing | 5 prohibited triggers → escalation + structured ticket with full context |
| Preserve a clear conversation and action record | Append-only turns, actions and tickets; retrievable via API and visible in the UI |
| Working agent / clickable prototype | Hosted on Render + one-command local run |
| Architecture and process flow | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Inputs, sources, assumptions | [Above](#inputs-sources-and-assumptions) |
| List of AI tools used | [Above](#ai-tools-used) |
| Structured ticket · source for its answer · audit trail | `tickets` table + `/api/tickets`; every action cites its rule; append-only ledger |

---

## Project structure

```
backend/
  main.py             FastAPI: SSE chat, REST audit reads, serves the frontend
  config.py           Loads .env before anything reads os.getenv
  agent/
    graph.py          LangGraph topology — every reply routed through decide
    prompts.py        One small prompt per node; shared grounding contract
    nodes/            identify · understand · facts · clarify · decide
                      escalate · respond · record
  policy/
    engine.py         The 6 rules + the authority gate (pure Python, no LLM)
    test_engine.py    The three scenarios + boundaries as tests
  records/ledger.py   Append-only SQLite: turns, actions, tickets
  data/               datapack.json — the only source of facts
  llm/provider.py     groq | ollama | mock, behind one interface
frontend/src/         React: Sidebar · Chat · ActionRecord · ThemeToggle
Dockerfile            Multi-stage: node builds the UI, python serves it
render.yaml           Render blueprint (free tier)
run.ps1 / run.sh      One-command local run (Windows / Unix)
```

---

## Deployment

The repo ships a multi-stage `Dockerfile` (Node builds the frontend, Python serves it as a
single service) and a `render.yaml` blueprint.

1. Push to GitHub.
2. Render → **New** → **Blueprint** → select this repo. It reads `render.yaml`.
3. Set **`GROQ_API_KEY`** when prompted (free key from [console.groq.com](https://console.groq.com)).
   It is marked `sync: false`, so it is never committed.
4. Wait for the build, then check `/healthz` reports `"llm_provider": "groq"`.

Setting `LLM_PROVIDER=mock` gives a zero-key deployment that still demonstrates the full policy
engine and audit trail.

**Why Render.** Hugging Face now requires a paid plan for Docker Spaces, Fly.io and Google
Cloud Run both require a credit card, and Koyeb's free tier is Postgres-only. Render free is
the only genuinely card-free Docker host, so the design works around its constraints rather
than pretending they don't exist.

---

## Known limitations

Stated plainly, because pretending otherwise would be worse than the limitations themselves.

- **Cold start.** Free instances sleep after 15 minutes idle; the next request waits ~1 minute.
- **Ephemeral audit trail.** Free instances cannot attach a disk, so the ledger resets when the
  container restarts. It is complete and correct *within* a visit. Fixing it properly means a
  paid instance with a disk mounted at `/var/data` (then set `DB_PATH=/var/data/skyassist.db`),
  or moving the ledger to Postgres.
- **No LLM fallback.** If the hosted model is rate-limited or misconfigured, the agent replies
  with a clear apology rather than a stack trace — but it does not fall back to the mock engine,
  and that failed turn is not written to the ledger.
- **Prototype execution.** Refunds, rebookings and vouchers are ledger writes. There is no
  payment gateway or reservation system behind them.
- **Single instance.** SQLite and in-process session state assume one process; this would need a
  shared database before scaling out.

---

## Further reading

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — the full design: layer diagram, node-by-node flow,
  the authority gate, escalation matrix, API contract, and requirement trace.
