# Demo video: click-by-click script (target 3:30–4:00)

## Before you record (10 minutes)
1. Close everything else. Turn on Do Not Disturb.
2. Terminal: `cd C:\Users\ankit\projects\centralign-agent` → `.venv\Scripts\activate` → `python -m sandbox`
3. Chrome: open `http://localhost:8000/runs` and make the window full screen (F11). Zoom to 90% if it feels crowded.
4. Recorder: **Clipchamp** (built into Windows), *Record* → *Screen and camera* (camera optional). Or use Xbox Game Bar: Win+Alt+R starts and stops.
5. Do one practice run first. Runs take 1–3 minutes, so **speed up the waiting parts** later in Clipchamp (select clip → Speed → 4×).

## Scene 1 (0:00–0:25): the hook. Show the Workforce page.
> "Everyone can build an agent that clicks buttons. I built AI employees for a pretend company, Acme Logistics. You hire one by writing a role file: what it's responsible for, which systems it may touch, which rules it follows and when it must ask a human. It does real work in real web apps, and it only says done after an independent check."

Hover the **Diya** and **Kabir** cards, then the **"How your workforce is governed"** panel.

## Scene 2 (0:25–0:50): open Diya's profile (click her card)
> "Diya is the accounts payable employee. These are her responsibilities and the only systems she can open, enforced in code. These are the business rules: bills over one lakh need the Finance Manager, over five lakh the CFO, and she can never delete records. And this is her trust ladder: autonomy is earned from verified work. Right now it recommends Supervised, because one of her earlier runs failed verification. The system is honest about its own track record."

## Scene 3 (0:50–2:10): the brief's task, live, with chaos and approval
1. Click **Workforce** → **Assign work** → pick **Diya** → click the **"Globex invoice into the ERP"** preset.
2. Open **Stress test** and turn on **Server error on save** and **Over approval limit**. Keep *Show the browser* on.
3. Click **Assign to Diya**. The run page opens.

> "This is the exact task from the brief. I've also injected a server error and made the invoice ₹1.85 lakh."

While it runs, point at:
- **the loop stepper** (Understand → Plan → Execute…): "it read the SOP first, then planned with exact success criteria."
- **"What the agent sees"**: "a real browser: inbox, PDF download, ERP form."
- **The approval card appears**: "the permission layer, not the model, stopped it. Over one lakh needs the Finance Manager." Type a note "Approved – Finance" → **Approve and continue**.
- **Activity shows a server error**: "the save failed with a 500. It doesn't retry blindly: it checks the bills list first so it never creates a duplicate, then retries."
- **The verifier step**: "now a *different* AI model, in a separate read-only browser, re-downloads the original PDF and checks every value."
- **The receipt**: "verified complete, with evidence for each criterion. One approval, about ten rupees of model cost."

## Scene 4 (2:10–2:40): the same code, a different job
Go to **Workforce** → **Recent work** → open the **Kabir** screening run (*"Screen the new applicants…"*), then open **TalentDesk** from *Systems*.
> "Same runtime, different role file. Kabir screened six applicants against the job description: two shortlisted, three rejected with reasons, and one marked Needs Info because his salary expectation was missing. It booked the strongest candidate on Thursday. That's what CentrAlign's Raj does."

## Scene 5 (2:40–3:15): it learns your rules
Show the README section **"It learns your company's rules"** (the table), or the **Inbox** if a proposal is pending.
> "When the invoice had no due date, Diya asked me once. I said Globex is always invoice date plus fifteen days. She proposed that as a company rule, and I approved it in the Inbox. Next time she didn't ask at all: twenty-six percent fewer steps and forty-three percent cheaper. She only learns what a human approves, so a malicious email can't rewrite company rules."

## Scene 6 (3:15–3:50): proof and honesty
Open `README.md` on GitHub → the **Evaluation** section.
> "Twenty-two scenarios, scored against the sandbox's real database, including five held-out tasks I wrote before running anything. The number I care about most is false successes: when it says done but isn't. My first full run scored ten out of fourteen and exposed real bugs. They're documented here with how I fixed them."

## Scene 7 (3:50–4:00): close
> "Next: Raj-style WhatsApp checks with candidates, always-on employees watching the inbox, and compiling verified runs into reusable skills. Thanks for watching."

## After recording
1. In Clipchamp, cut the mistakes and speed up the waiting (4×). Export at 1080p.
2. Upload to YouTube as **Unlisted** (or Google Drive with "Anyone with the link").
3. Paste the link at the top of README.md (replace `_add link_`), commit and push.
