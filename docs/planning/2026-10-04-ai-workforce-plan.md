# Final plan: from "AI worker demo" to "AI Workforce" (CentrAlign-aligned)

This plan combines four specialist reviews: a company researcher, a senior PM, a senior product designer, and a mock hiring-panel reviewer.

## Why change anything?
- **Competition:** about 5 other candidates have public repos for this exact assignment, and **all of them built the same invoice→ERP demo**. Ours is already stronger (real browser, verifier, chaos tests), but it still *looks* like the same category.
- **CentrAlign's own language** (centralign.ai): "AI employees act", "a roster of specialized workers", and you *Configure* each employee by defining "**responsibilities, permissions, business rules, escalation paths and human checkpoints**". They also offer Understand → Connect → Configure → Deploy, a Permission Layer, Human Escalation, audit trails, and "pay only for work actually completed".
- **Reviewer critique:** the project scores about 7/10 per criterion. It loses points on a few credibility gaps a reviewer *will* probe:
  - a crash path in `finish`
  - the verifier isn't truly read-only
  - an "Rs. 1,85,000" amount parsing bypass
  - an unenforced approval denial
  - a "14/14" result that was stitched together from re-runs

## The pitch (one sentence)
> **"An AI Employee runtime: you *hire* an AI employee by writing a role file (responsibilities, permissions, business rules, escalation paths, human checkpoints), and the same runtime does the work in real company apps, verified by an independent checker, with a full audit trail."**

## Two named AI employees (same code, different role files)
| Employee | Role | Systems | Escalates to |
|---|---|---|---|
| **Diya** | Accounts Payable Associate | AcmeMail, Ledgerly ERP | Finance Manager (Meera Rao) |
| **Kabir** | Recruiting Coordinator ("Raj-style") | AcmeMail, HireHub, TalentDesk | Hiring Manager (Vikram Desai) |

(We don't reuse their product name "Raj". In the interview, say "Raj-style".)

## Work packages
### P1 Credibility fixes (must; about 1.5h, tonight)
1. Fix amount parsing (`Rs. 1,85,000`, lakh) and add tests (`worker/policy.py`).
2. Make the policy consequential-check also catch any POST form submit, not only button labels (`policy.py`, `browser.py`).
3. **Make the verifier read-only at the network level:** block every non-GET request in its browser (`browser.new_isolated_page`). Optionally run it on a different model (GLM-5).
4. Never lose a report: handle a malformed `finish()` and any crash, so a report is always written (`runtime.py`).
5. Enforce a denied `request_approval` (`runtime._deterministic_checks`).
6. Learned facts go to a review queue (`memory/_proposed/`), not straight into memory.
7. Make real git commits from now on.

### P2 "Hire an AI employee": roles as config (must; about 2.5h, morning)
- `roles/ap_associate.yaml` and `roles/recruiting_coordinator.yaml` with the keys name, title, reports_to, responsibilities, systems, tools, knowledge (SOPs), business_rules, escalation and human_checkpoints.
- `worker/role.py` loads the role. The runtime filters tools, the prompt carries the role, memory search is limited to the role's SOPs, and policy adds role rules plus an **app boundary** enforced in code. Kabir *cannot* touch the ERP.
- `--role` on the CLI, plus a `role:` field in every eval scenario. New scenario **B1_out_of_role**: Kabir is asked to enter an invoice, refuses, and routes it to AP.

### P3 Workforce console UI (must; about 2h, morning; senior-designer spec)
- **Workforce home:** an employee roster with live status ("Entering bill GX-1042…"), verified-work counts, an "Assign work" panel, and stress-test chaos behind a disclosure.
- **Inbox:** every approval and question from every employee in one place, with Approve/Deny.
- **Employee profile:** the role definition (responsibilities, permissions, rules enforced in code, escalation, checkpoints), a pipeline (Intake → Validation → Approval → Posting → Reported), and the work history/audit log.
- **Run page:** a reskin that ends in a **verified receipt**.
- Dark default, no emoji, accessible contrast and focus states.

### P4 3-way match: PO + GRN reconciliation (optional; cut-line 12:15)
This is CentrAlign's finance pipeline: Validation, Reconciliation, then flagging a mismatch. Invoices carry a PO number; if goods received < invoiced, the bill goes "On Hold – Exception" and is flagged. Scenarios M1 and M2.

### P5 Honest evaluation (runs in the background)
- Run the full suite **3 times** overnight (about 90 minutes, about $4–5 of AWS credits). Report pass rate per scenario and the **false-success rate** as the headline. Show failures honestly.
- Final short re-run after P2/P3 (n=2 on the key scenarios).

### P6 Ship
README rewrite in CentrAlign's language, refreshed screenshots, the video, push, and submit.

## Timeline (today, 4 Oct)
| Time | Who | What |
|---|---|---|
| 01:30–03:00 | Claude | P1 fixes + tests, commit, start the overnight eval |
| 03:00–09:00 | You sleep | the eval runs (laptop plugged in, sleep mode off) |
| 09:00–09:30 | Claude | read results, fix repeated failure patterns |
| 09:30–12:00 | Claude | P2 roles |
| 12:00–13:30 | Claude | P3 UI (+ P4 only if ahead of schedule) |
| 13:30–14:30 | Claude | README, screenshots, final eval; **code freeze 14:30** |
| 14:30–15:30 | You | record the video (new storyline below) |
| 15:30–16:30 | Both | push, add links, **submit** (an hour of buffer before 17:30) |

## New 4-minute video storyline
1. **0:00** "Not a copilot. You *hire* AI employees." Show the roster: Diya and Kabir.
2. **0:20** Open Diya's role file: responsibilities, permissions, rules, escalation, checkpoints. "This is Configure."
3. **0:50** Assign Diya the ₹1.85L invoice. Live: she reads the SOP, the policy gate fires, the request appears in the Inbox, you approve, and she ends with a verified receipt.
4. **1:50** The "fake Saved!" stress test: the read-only verifier catches it and Diya repairs it.
5. **2:30** Kabir on the same runtime screens applicants and books a call. Then ask Kabir to enter an invoice: he's refused by the permission boundary.
6. **3:10** The audit trail, the evidence report, and the honest eval table with 0 false successes.
7. **3:40** Next steps: Raj-style WhatsApp intent checks, a review queue for learned facts, connectors.

## Interview talking points (CentrAlign language)
1. **Roles are config; the runtime is generic.** A new AI employee is a YAML file plus SOPs.
2. **The Permission Layer lives outside the LLM.** Prompts are advice; code is the guarantee.
3. **Human Escalation is a feature.** "Blocked" is the correct, measured outcome when a human must decide.
4. **Trust is measured:** the false-success rate, chaos scenarios, and failures shown honestly.
5. **Observability:** a ledger, an audit trail and evidence for every action. "Pay for verified work."
