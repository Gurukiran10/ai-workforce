# Demo video script (about 4 minutes)

**Setup before recording:**
- Terminal 1: `python -m sandbox`
- Browser tab A: `http://localhost:8000/runs`
- Terminal 2: ready to run the commands below
- Use OBS or the Windows Game Bar (Win+G) to record the screen plus your voice.

## 0:00–0:25 · Problem and what I built
"Company work is spread across inboxes, ERPs and portals. I built Acme Worker, an AI employee that takes a short request and finishes the work by operating the company's web apps itself. It follows company SOPs, asks a human when it should, and only says 'done' after an independent verifier re-checks the systems. Everything runs against a sandboxed fake company, Acme Logistics, so no real credentials are involved."

Show the sandbox quickly: AcmeMail inbox, Ledgerly bills, HireHub applicants, TalentDesk.

## 0:25–0:50 · Architecture
Show the README diagram. "It's one loop: understand from company memory, plan with checkable success criteria, act through generic browser tools, observe HTTP results, adapt. A deterministic policy gate and a duplicate-action ledger sit outside the LLM. A separate read-only verifier checks the outcome. Task knowledge lives in markdown SOPs, not in code."

## 0:50–2:00 · Main run: invoice with a server error and an approval
```bash
python -m worker run "Find the latest invoice from Globex, extract the amount and due date, enter it into our accounts system, and tell me once it is done." --chaos flaky_submit,over_threshold --human web --headed
```
Open the printed `/runs/<id>` link. Narrate these moments:
- It searches the SOPs and writes a plan with exact success criteria.
- It downloads and reads the PDF and records facts with their sources.
- The policy gate pauses for approval: "₹1,85,000 is above the ₹1,00,000 limit." Click **Approve** in the viewer.
- The ERP returns a **500 error**. The agent sees it, checks the bills list, and only then retries.
- The verifier opens a fresh browser, confirms exactly one bill, and the result is **VERIFIED**.
- Open the **evidence report**.

## 2:00–2:30 · Silent failure caught by verification
```bash
python -m worker run "<same invoice task>" --chaos silent_drop
```
"The ERP says 'Saved!' but drops the record. The worker believes it's done; the verifier finds no bill and sends it back. It re-enters the bill, and verification passes." (You can show this from an eval run report if you prefer.)

## 2:30–3:15 · Same code, different job: recruiting
```bash
python -m worker run "Screen the new applicants for the Backend Engineer role against the job description, record each of them in TalentDesk with the right stage, and book a screening call for the strongest candidate in the first free Thursday slot." --reset --headed
```
"No code changed; it read the JD and the screening SOP." Show the ATS: shortlisted and rejected candidates, Arjun set to **Needs Info** because his CTC is missing, and Priya booked on Thursday.
Optionally run `python -m pytest -q` to show the test that fails if task-specific code enters `worker/`.

## 3:15–3:40 · Safety
Show the F9 (prompt injection) report: the malicious email was ignored and flagged. Show H1: the bank-change request came from a look-alike domain and was refused.

## 3:40–4:10 · Results and next steps
Open `evals/results/<latest>.md`: pass rate, **false-success rate**, cost and time per run.
"Next I'd add API and MCP connectors, a job queue with sandboxed browsers, learning from human corrections, and desktop computer use. Limitations are listed in the README."
