# Acme Workforce: AI employees that do the work, check in when a decision is yours, and prove the result

*Submission for the CentrAlign AI Engineering Intern problem, "Autonomous AI Task Worker".*

You hire an AI employee by writing a **role file**: its responsibilities, the systems it may use, the business rules it follows, who it escalates to, and its human checkpoints. The same runtime then does the work in real company web apps, through a real browser:

- It **plans** from company SOPs.
- It **acts** in mail, ERP, a job portal and an ATS.
- It **recovers** from failures without duplicating records.
- It **asks** when a decision belongs to a human.
- It reports "done" only after an **independent verifier on a different model** has re-checked the live systems.
- When you answer a question once, it **proposes a rule for company memory**. After you approve it, the employee stops asking.

> **Demo video:** _add link_ · **Example evidence:** [`runs/sample-*/report.html`](runs/) · **Run without any API key:** see [Browse the sample runs](#browse-the-sample-runs-no-api-key-needed)

![Live run page: plan, independent verification and receipt](docs/screenshots/run-invoice-approval.png)

| Your AI workforce (roster, assign work, governance) | Employee profile: role, trust ladder, rules, history |
|---|---|
| ![console](docs/screenshots/console.png) | ![employee](docs/screenshots/employee.png) |

### Where to find what the brief asks for
| Requirement | Where |
|---|---|
| Source code + setup and run | This repo · [Quickstart](#quickstart) |
| Architecture | [Architecture](#architecture) |
| Technical and design decisions | [Key design decisions](#key-design-decisions-and-what-i-rejected) |
| Demo video | Link at the top |
| Known limitations | [Known limitations](#known-limitations) |
| What I'd build next | [What I'd build next](#what-id-build-next) |
| Assumptions | [Assumptions](#assumptions) |
| Models, APIs, frameworks | [Models and components](#models-apis-and-components-used) |
| Evidence that it works | [Evaluation](#evaluation): development suite, **held-out set frozen before any run**, false-success rate |

---

## The two AI employees
| | **Diya**, Accounts Payable Associate | **Kabir**, Recruiting Coordinator |
|---|---|---|
| Role file | [`roles/diya.yaml`](roles/diya.yaml) | [`roles/kabir.yaml`](roles/kabir.yaml) |
| Systems (enforced in code) | AcmeMail, Ledgerly ERP | AcmeMail, HireHub (Naukri-like portal), TalentDesk ATS |
| Knowledge | AP SOP, vendor master notes | Screening SOP, job description |
| Human checkpoints | Bills > ₹1,00,000 (Finance Manager), > ₹5,00,000 (CFO), any bank-detail change | Emails to candidates, shortlisting with missing information |
| Typical task | *"Find the latest invoice from Globex, extract the amount and due date, enter it into our accounts system, and tell me once it is done."* (the brief's example) | *"Screen the new applicants for the Backend Engineer role, record each in TalentDesk with the right stage, and book a screening call for the strongest one."* |

Both employees run on **the same code**. A unit test fails if any app, vendor or task name appears in `worker/`. A task is routed to the right employee by its wording, and an employee handed out-of-role work stops and names the right colleague (scenario `B1_out_of_role`).

## What makes it different
1. **The verifier is independent, not a self-review.** It runs on a different model (GLM-5 checks Kimi K3's work) in a fresh browser context that blocks every non-GET request at the network level. It has its own empty workspace, so it must re-download the source document itself. It adds its own checks derived from the SOP and looks for regressions and side effects. The worker's notes reach it only as "unverified hints".
2. **No value is written unless the employee observed it, or code computed it.** Before any consequential click, every form value must appear in a document, page or human answer the employee actually saw. Derived values, such as a due date of invoice date + 15 days, come from a `calculate` tool, so code does the arithmetic, not the model. Each value is recorded with its formula.
3. **It learns your company's rules, with a human in the loop.** When a human answer settles something the SOPs don't cover, the employee files a proposal. A human accepts it in the Inbox, and only then does it enter company memory. Unapproved proposals are never retrieved. Measured end to end ([`scripts/demo_learning.py`](scripts/demo_learning.py)):

   | Same invoice with no due date | Questions to a human | Steps | Cost | Verified |
   |---|---|---|---|---|
   | Run 1: before learning | 1 | 27 | $0.180 | ✅ |
   | Run 2: after the rule was approved | **0** | **20** | **$0.103** | ✅ (due date cited "learned rule") |

4. **Trust is earned and visible (the trust ladder).** Each employee is either *Supervised* (every consequential action needs approval) or *Standard* (only policy-flagged actions do). The console recommends a level from the employee's verified track record. A failed verification in the last 10 runs recommends dropping back to Supervised. A human changes the level.
5. **Safety lives in code, not in the prompt.** These are all deterministic and outside the LLM:
   - the permission layer (`config/policies.yaml`: tiered approval limits, approvers, a delete ban, POST-form detection)
   - a duplicate-action ledger with check-before-retry
   - binding approval denials
   - per-role data boundaries
   - a circuit breaker for loops
   - crash safety that always writes a report

---

## Quickstart
```bash
python -m venv .venv
.venv\Scripts\activate                 # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
copy .env.example .env                 # add ONE LLM credential (see "LLM configuration")
```
Terminal 1 starts the sandbox company and the console:
```bash
python -m sandbox                       # console: http://localhost:8000/runs
```
Then assign work in the console (with *Show the browser* on to watch the employee), or use the CLI:
```bash
python -m worker run "Find the latest invoice from Globex, extract the amount and due date, enter it into our accounts system, and tell me once it is done." --reset --headed --human web
```
- `--role diya|kabir` assigns the task to a specific employee. The default is auto-routing.
- `--chaos flaky_submit,over_threshold` injects real-world mess. The full list is at `/__admin/chaos`, or under *Stress test* in the console.
- `--human web` sends approvals and questions to the console Inbox instead of the terminal.

### Browse the sample runs (no API key needed)
`python -m sandbox`, then open http://localhost:8000/runs. The committed runs in `runs/sample-*` replay in the run page, and each has a full evidence report. No model calls are made.

### Tests and evals
```bash
python -m pytest -q                     # 53 unit tests: no LLM, no browser (sandbox-dependent ones skip)
python tests/smoke_tools.py             # tool-level smoke test against the sandbox (no LLM)
python -m evals.run --list              # 22 scenarios
python -m evals.run --repeat 2 --tag mine --max-cost 10
python scripts/demo_learning.py         # learning loop, end to end (2 runs)
```

### LLM configuration
`config/agent.yaml` (`llm.provider`), or `LLM_PROVIDER=...` per run.

| provider | model | credential in `.env` |
|---|---|---|
| `bedrock_converse` (default) | Worker: **Kimi K3** (`us.moonshotai.kimi-k3`). Verifier: **GLM-5** (`zai.glm-5`) | `AWS_BEARER_TOKEN_BEDROCK` + `AWS_REGION` |
| `anthropic` / `bedrock` / `claude_platform_aws` | Claude (supported; it was the original target, but Marketplace activation failed on the test AWS account) | `ANTHROPIC_API_KEY` / AWS credentials |
| `gemini`, `groq`, `openrouter` | any OpenAI-compatible model | `GEMINI_API_KEY` / `GROQ_API_KEY` / `OPENROUTER_API_KEY` |

---

## Architecture
```
 Request ──▶ route to an AI employee (roles/*.yaml: responsibilities, systems, knowledge, checkpoints, autonomy)
                │
┌───────────────▼──────────────── Runtime: one ReAct loop with explicit state ────────────────────────────┐
│ RunState: goal · plan · success criteria (exact values) · facts{value, source} · evidence · action ledger │
│                                                                                                         │
│  Context (compacted) ─▶ LLM adapter ─tool call─▶ Guards ─▶ Provenance check ─▶ Permission layer ─▶ Human  │
│        ▲                (Bedrock Converse /     (loops,     (value observed     (policies.yaml:       (Inbox │
│        │                 Anthropic / OpenAI-     budgets)    or computed?)       tiers, approvers,     / CLI) │
│        │                 compatible)                                             role boundary)              │
│   observation ◀── Perception: numbered elements + text + HTTP status + downloads ◀── Playwright browser  │
│                                                                                                         │
│  finish() ─▶ deterministic checks (claims, duplicates, binding denials)                                   │
│          ─▶ Verifier: DIFFERENT model · fresh browser · network read-only · own workspace · SOP checks     │
│               pass ─▶ receipt + evidence report          fail ─▶ back to the employee (≤2 repairs)         │
│                                                                                                         │
│  Learning: human answer ─▶ propose_rule ─▶ memory/_proposed ─▶ human accepts ─▶ memory/learned_rules.md  │
└───────── Audit trail: runs/<id>/trace.jsonl · screenshots · report.html · result.json ──────────────────┘
```

**Mapping to CentrAlign's platform vocabulary**
| CentrAlign component | Here |
|---|---|
| Reasoning Engine | ReAct loop with explicit plan and success criteria (`worker/runtime.py`) |
| Workflow Engine | SOPs in `memory/` decide the steps; nothing is hard-coded |
| Company Memory / Knowledge Retrieval | `memory/*.md` + BM25, scoped per role, plus human-approved `learned_rules.md` |
| Permission Layer | `config/policies.yaml` + role data boundaries, enforced in `worker/policy.py` and `worker/tools.py` |
| Human Escalation | Approvals, questions and rule proposals in the Inbox; denials are binding |
| Tool Execution | Generic browser and file tools (`worker/tools.py`, `worker/browser.py`) |
| Observability | `trace.jsonl`, live run page, evidence report, audit log, per-employee trust record |

### Repository layout
```
roles/      AI employee definitions (responsibilities, systems, knowledge, checkpoints, autonomy)
worker/     the generic runtime: loop, tools, perception, policy, provenance, verifier, learning, LLM adapters
memory/     company memory: SOPs, job description, vendor notes, directory, learned_rules.md
config/     agent.yaml (models, budgets) · policies.yaml (permission layer)
sandbox/    the pretend company: AcmeMail, Ledgerly ERP, HireHub, TalentDesk + chaos flags + admin API
viewer/     operator console: workforce, Inbox, employee profiles, live run page, audit log
evals/      22 scenarios (17 development + 5 held-out) scored against sandbox ground truth
tests/      53 unit tests incl. fake-LLM runtime tests and a "no task-specific code" guard
```

---

## Key design decisions (and what I rejected)
| Decision | Why | Rejected |
|---|---|---|
| **Roles as config** (`roles/*.yaml`) | A new AI employee is a file plus SOPs, not code. This mirrors "define responsibilities, permissions, business rules, escalation paths and human checkpoints" | Hard-coded workflows per task (fake autonomy) |
| **DOM perceived as numbered elements** + text + HTTP status | Fast, cheap, precise and debuggable on any server-rendered app, with no selectors | Screenshot-only computer use: slower and coordinate-flaky. Kept as a future fallback for desktop and canvas UIs |
| **One ReAct loop with explicit plan state** | Adapts step by step while the plan and criteria stay inspectable | A rigid planner/executor breaks when reality differs from the plan |
| **Plain Python, no agent framework** | The control flow is the product. I can explain, debug and change every line | LangChain/LangGraph hide the loop |
| **Verifier on a different model, read-only at the network level** | "Done" must mean *observed* done, judged by something that can't grade its own homework or change data | Self-reported success, or a same-model judge sharing the worker's files |
| **Provenance check + code-computed values** | Stops hallucinated numbers at the point of writing, and keeps derived values auditable | Trusting extracted values, or letting the model do date maths |
| **Permission layer in YAML, evaluated in code** | A prompt injection can't talk past code. Customers change rules without code changes | Asking the model "is this allowed?" |
| **Human-approved learning** (proposal → Inbox → memory) | The employee gets cheaper to supervise over time without letting a poisoned email rewrite company rules | Auto-writing "facts" to memory |
| **Duplicate-action ledger** | A retry of an identical write requires looking at another page first and a written reason. This prevents double bills after a 504 "ghost save" | Blind retries |
| **Model-agnostic adapters** | It survived real access problems: Claude blocked by AWS Marketplace billing, Groq and Gemini free tiers too small. Switching is one config line | Coupling to one vendor SDK |

---

## Evaluation
Each scenario is a natural-language task plus sandbox chaos, scripted human responses and an **oracle that checks the sandbox's real database**, which the employee never sees. The headline metric is the **false-success rate**: runs where the employee reported a verified success but the ground truth disagrees.

| Group | Scenarios |
|---|---|
| Brief's task + failures | T1 base · F2 500 on save · F2b 504 but saved (no duplicate) · F3 ERP says "Saved!" but drops it · F4 form relabelled · F5 revised invoice + look-alike vendor |
| Human-in-the-loop | F6 over limit, approved · F7 over limit, denied → clean stop · F8 missing due date → must ask |
| Safety | F9 prompt-injection email · H1 bank-change from a look-alike domain |
| Recruiting (same code) | T2 screen 6 applicants + book the strongest · R2 existing candidate · R4 slot taken · Q1 "who applied?" (read-only) · Q2 role that doesn't exist (must not hallucinate) |
| Boundaries | B1 recruiting employee handed an accounts task → refuses, names the right colleague |
| **Held-out (frozen before any run)** | HO1 bill already booked · HO2 "how much do we owe Stark Freight?" · HO3 the brief's task in casual wording · HO4 strongest applicant, read-only · HO5 impossible payment request |

<!-- METRICS:START -->
_Results are generated from `evals/results/*.json` by `scripts/update_readme_metrics.py` (pending the final run)._
<!-- METRICS:END -->

**How we got here (honest history).**
- The first full run (03-10, 14 scenarios) scored **10/14 with 0 false successes**. The four failures were real bugs:
  - `ask_human` crashed in the logger; the agent refused to guess and stopped safely.
  - The duplicate check flagged a justified retry.
  - Recruiting ran out of a 45-step budget.
  - A sandbox bug caused one **false success**: the ATS dropdown lacked a stage, so a later save regressed it, and the verifier passed it because the worker's own criterion was wrong.
- That run led to the second round of work:
  - the independent different-model verifier with its own SOP-derived criteria
  - the provenance check
  - binding denials and crash safety
  - honest repeat-based evals
  - the held-out set
- Integration testing of the stricter verifier first **failed 2 of 3 correct runs**, because it ran out of steps and was given criteria nobody could observe. The fixes were a larger budget, a "report now" warning, observable-state-only criteria, and approvals taken from the runtime's audit trail.
- The learning loop's first version was **safely blocked by the provenance check**, since a computed date isn't "observed". That led to the `calculate` tool.

---

## Models, APIs and components used
- **LLMs (Amazon Bedrock, Converse API via boto3):**
  - worker: **Kimi K3** (Moonshot AI)
  - verifier: **GLM-5** (Z.ai)
  - also tried: Amazon Nova Pro, DeepSeek V3.2, GPT-OSS-120B, Gemini Flash (AI Studio), GPT-OSS-120B (Groq)
  - Claude is supported through the Anthropic SDK.
- **Browser:** Playwright (Chromium, sync API).
- **Sandbox, console:** FastAPI, Jinja2, uvicorn, vanilla HTML/CSS/JS. **PDFs:** fpdf2 (generate), pypdf (read). **Memory:** rank-bm25. **Config:** PyYAML.
- I built this with Claude Code as an AI coding assistant, as the brief allows, including parallel review and implementation agents. I can explain and modify every part.

## Assumptions
- Everything runs against a local pretend company. There are no real systems, credentials or personal data.
- The company apps are server-rendered English web apps, and sessions are assumed authenticated (no login screens).
- One task runs at a time. Approvals and questions are answered by one operator.
- "Latest invoice" means latest by invoice date. SOPs and human-approved learned rules are the source of business rules.

## Known limitations
- **No login or session expiry** in the sandbox. Real portals (Naukri, ERPs) need credential vaults and re-authentication.
- **Web only.** Desktop and canvas apps need a screenshot-based computer-use fallback.
- **The verifier is still an LLM** (a different one). Deterministic read-back checks generated from the success criteria would make it stronger.
- **Learned rules are free text** retrieved by BM25. There's no conflict detection between rules and no expiry or versioning yet.
- **`business_rules` in a role file are shown, not enforced per role.** The permission layer applies all policy rules to everyone.
- **Results are rates over few repeats.** LLMs are nondeterministic, so read the pass counts, not a single run.
- **Each task re-reasons from scratch.** A verified run isn't yet compiled into a replayable skill.

## What I'd build next
1. **Raj-style intent verification:** a messaging channel (WhatsApp/email) so Kabir confirms notice period, salary expectations and counter-offers before shortlisting.
2. **Always-on employees:** a queue and scheduler so Diya watches the AP inbox and processes new invoices unprompted, reporting via the Inbox.
3. **Skills from verified runs:** compile a verified trace into a parameterised procedure, replay it cheaply, and repair only the step that breaks.
4. **Connectors:** API or MCP when a system has one, the browser only when it doesn't, behind the same permission layer and verifier.
5. **Production plumbing:** credential vault and logins, per-tenant sandboxed browsers, resumable runs from `trace.jsonl`, OpenTelemetry, and evals in CI per workflow.
6. **Trust ladder level 3 (Autonomous within limits),** gated on a measured false-success rate per workflow.
