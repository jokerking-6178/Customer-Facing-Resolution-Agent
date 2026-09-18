# SkyAssist — Airline Disruption Resolution Agent

**Assignment 3 · Agentic AI Factory (AIONOS) · Customer-Facing Resolution Agent**

SkyAssist handles customers hit by airline disruptions on **Wednesday, 23 September 2026**:
a cancelled Delhi–Goa flight, a 4-hour Mumbai–Bengaluru delay, and a 6-hour Delhi–Hyderabad
delay. It understands the customer's intent, asks only necessary questions, uses only the
supplied data and policies, executes the correct next action within its authority, stays calm
with angry customers, escalates when authority is missing, and preserves a complete
conversation and action record.

**The one design rule: the LLM talks, the code decides.** No compensation amount, waiver, or
refund is ever computed by the model — every rupee comes from a deterministic, unit-tested
policy engine, and every fact comes from the supplied data pack.

Full design: see [ARCHITECTURE.md](./ARCHITECTURE.md).

---

## Quickstart (local)

```bash
# 0) one-time
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cd frontend && npm install && npm run build && cd ..

# 1) run — pick a provider
LLM_PROVIDER=mock  python -m uvicorn backend.main:app --port 8000   # no LLM needed
LLM_PROVIDER=ollama python -m uvicorn backend.main:app --port 8000  # local Ollama (llama3.1:8b)
LLM_PROVIDER=groq   GROQ_API_KEY=gsk_... python -m uvicorn backend.main:app --port 8000
```

Open <http://localhost:8000>. Or use the one-command script:

```bash
./run.sh            # mock provider — instant, no LLM
./run.sh ollama     # local Ollama (pull `ollama pull llama3.1:8b` first)
```

### Windows (PowerShell)

```powershell
.\run.ps1                       # creates the venv, builds the UI, serves on :8000
$env:LLM_PROVIDER = "ollama"; .\run.ps1    # pick a different engine
```

Or manually:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
cd frontend; npm install; npm run build; cd ..
$env:LLM_PROVIDER = "mock"
.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8000
```

Frontend dev mode (hot reload): `cd frontend && npm run dev` (proxies `/api` and `/healthz` to :8000).

## Tests

```bash
python -m pytest backend -q          # macOS / Linux
```

```powershell
.venv\Scripts\python.exe -m pytest backend -q    # Windows
```

`backend/conftest.py` forces the mock provider and a throwaway database, so the suite never
needs an LLM, a key, or a network — and never writes to your real ledger.

The three scored scenarios are the acceptance tests (57 tests): policy-engine tests run
without any LLM; graph tests run the full pipeline with the deterministic mock provider.
Coverage includes the threshold boundaries (exactly 3h / 5h / ₹1,500), the sanitizer that
guards the authority gate against malformed model output, the two-question clarification
cap, ticket creation, and once-per-session idempotency.

## Deploy (Render)

The repo ships a Dockerfile (multi-stage: Node builds the frontend, Python serves it as one
service) and a `render.yaml` blueprint.

1. Push this repo to GitHub.
2. Render → New → Blueprint → select the repo.
3. Set the `GROQ_API_KEY` env var when prompted (a free-tier key from console.groq.com works).
4. The service builds and serves the full app on one URL.

`LLM_PROVIDER=mock` also works on Render if you want a zero-key demo deployment.

## Demo script

The UI has one-click preset buttons for all three scored scenarios:

| # | Customer | Situation | Expected agent behaviour |
|---|----------|-----------|---------------------------|
| 1 | Priya Nair (Gold) | SK-204 cancelled; furious; wants cash refund **+ free business upgrade** | Refund executed (7 business days, original method); upgrade declined — beyond stated policy; priority rebooking offered |
| 2 | Arvind Kulkarni (Silver) | SK-118 delayed 4h; wants a hotel | ₹500 meal voucher + lounge access issued; hotel declined (applies only above 5h) |
| 3 | Meher Kaur (Platinum) | SK-305 delayed 6h; wants a **full night's hotel** and a higher-fare flight (**₹2,000 fare difference**) | Hotel for the 6 delayed hours only — full night declined; fare waiver of ₹2,000 escalated (agent limit is ₹1,500); priority rebooking free |

Also try: a legal threat (immediate escalation, Sample C style, raised as a **high-priority
ticket**), asking for a refund to a different card (prohibited → escalate), and a bare "my
flight got cancelled" (the agent asks **one** question, and stops asking after two).

The right-hand panel shows the append-only action record — every executed, declined, escalated,
and clarified action with the rule that authorized it, plus the escalation ticket reference.

### Audit trail

| Endpoint | Shows |
|----------|-------|
| `GET /api/sessions` | every session handled |
| `GET /api/sessions/{id}` | full transcript **with the verdicts that drove each turn** |
| `GET /api/actions` | the whole action ledger (or `?session_id=` for one) |
| `GET /api/tickets` | structured escalation tickets (or `?session_id=`) |

Each escalation creates a ticket (`SKY-0001`, …) carrying the conversation history, booking
facts, the rules checked, the reason, and a priority — the packet a human agent picks up.

## Stack

| Layer | Choice |
|-------|--------|
| Frontend | React 18 (JSX), esbuild build, Vite dev server |
| API | FastAPI, SSE streaming |
| Agent | LangGraph state machine (8 nodes; every reply routed through the authority gate) |
| Decisions | Pure-Python policy engine (6 rules + authority gate) |
| Data | The assignment data pack as typed JSON; SQLite ledger + escalation tickets |
| LLM | Provider-switchable: Ollama (local) / Groq (hosted) / mock (tests) |

## Inputs, sources and assumptions

- All facts come exclusively from the Assignment 3 data pack (`backend/data/datapack.json`).
  Nothing is invented; out-of-pack questions get an honest "I don't have that information."
- The data pack lists Arvind's PNR as `TR1190B` in his profile but `TR11390B` in the Scenario 2
  text — normalized to `TR1190B` (documented as a data discrepancy).
- **No flight schedules or fares were supplied**, so none are modelled. The agent says
  "the next available flight within 24 hours" — exactly the rule's own wording — and never
  names a specific replacement flight number, time, or seat. There is deliberately no
  schedule accessor in `backend/data/loader.py` for anything downstream to reach for.
- **Fare differences are customer-stated and unverified.** Nothing in the pack prices a
  flight, so a figure like the ₹2,000 in Scenario 3 can only come from the customer. It is
  recorded with `fare_difference_source: "customer_stated"` on the verdict, in the ledger,
  and in the escalation ticket. A waiver request with no establishable amount escalates
  rather than auto-approving.
- Delay boundaries at exactly 3h / 5h are treated as "not more than" — the pack says "under
  3 hours" and "more than 3/5 hours", leaving the exact boundary undefined, so the agent
  resolves it conservatively (3h → voucher only; 5h → no hotel). Both are unit-tested.
- Refunds and rebookings are ledger writes in a prototype — no real payment or PSS integration.
- The sample conversations A/B/C from the pack are used **for tone only**, never as a source
  of facts or policy, exactly as the pack instructs.

## AI tools used

- An AI assistant was used to draft the architecture (see ARCHITECTURE.md) and transcribe the
  data pack into JSON.
- An AI code assistant was used for boilerplate (FastAPI routes, React components).
- An AI assistant was used to audit the implementation against the brief and data pack, and
  to apply the resulting fixes (policy-integrity, grounding, audit-trail and packaging work).
- Runtime LLMs: Ollama `llama3.1:8b` (local demo) and Groq `llama-3.3-70b-versatile` (hosted).
  A deterministic `mock` provider backs the test suite and needs no model at all.

## Project structure

```
skyassist/
├── backend/
│   ├── main.py            FastAPI app: SSE chat, REST reads, serves frontend/dist
│   ├── agent/             LangGraph graph, state, 8 nodes, prompts
│   ├── policy/            The 6 rules + authority gate + scenario tests
│   ├── data/              datapack.json (the only source of facts)
│   ├── records/           Append-only SQLite ledger: turns, actions, escalation tickets
│   └── llm/               Provider layer: ollama | groq | mock
├── frontend/              React (Vite dev, esbuild prod build)
├── ARCHITECTURE.md        Full architecture document
├── run.sh / run.ps1       One-command local run (macOS-Linux / Windows)
├── Dockerfile             Multi-stage: node build + python serve
└── render.yaml            Render blueprint
```
