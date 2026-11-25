# Approval card for delegated online purchases

IIS Assignment 2 prototype · Student 3160603 · README prose: about 1110 words (code and commands not counted)

A browser agent buys colour catcher sheets on a person's behalf. Before payment it shows a card that says what was ordered **and which choices were made for the person**, such as a shop's pre-selected Subscribe & Save. A rule-based validator checks the real checkout before Buy is allowed. The design comes from my Lab 2 storyboards and my Lab 3 SPEC v2; the problem comes from my A1 literature review.

## Project status

| Part | Status |
|---|---|
| "Here's what I understood" card: asks only about missing details; closing it pauses the task | Implemented |
| Plan, step log, comparison of readable offers, disclosure of the unreadable listing | Implemented |
| Validator rules R1–R8 from SPEC v2 (`validator.py`) | Implemented |
| Disclosure approval card: order, choices made for you with their origin, problems, checks | Implemented |
| Buy / Change / Cancel / Retry; approval tied to one order snapshot; subscription terms acknowledgement | Implemented |
| Baseline card toggle (plain order summary, for the A3 comparison) | Implemented |
| Run log of every step (`logs/run-log.jsonl`) | Implemented |
| Request parsing and choice explanation (the "model") | **Simulated**: deterministic rules in `mock_model.py`, no LLM |
| Shop website, browser tool, basket and orders | **Simulated**: made-up listings in `data/listings.json`, `mock_shop.py` |
| Real LLM, real browser automation (e.g. Playwright on a live site), notifications, user study | **Planned**, not built |

Failure branches: case D (Subscribe & Save stays on after the agent clicks one-time) can be triggered from the **Demo scenario** menu. Cases C, F and H run only in the automated tests.

Not finished: both conditions show the same plan and step log; the baseline only hides the validator's result (the check step reads "Prepared the checkout"). Whether that is equal enough for an A3 comparison is not yet decided.

## Technology stack

- **Python 3 standard library** (`http.server`, `json`, `unittest`). No packages to install.
- **Plain HTML, CSS and JavaScript** for the page. The page only displays state; every decision is made on the server, so the page cannot skip a check.
- **No AI model at run time.** The parts an LLM would do (parse the request, write the one-line reason) are simulated so every run is reproducible. Undecided: which LLM to use if this becomes a live prototype.

## Running or inspecting the work

```
python3 app.py
# open http://127.0.0.1:8000
python3 -m unittest -v      # 24 tests: SPEC cases A–H, cancel, budget, change, unknown outcome, manual-check fixes
```

Things to try:

1. Click the first example ("Get me some colour catchers, compare prices.") and Send. Choose *You choose*, *1 pack*, *One-time*, *No limit*.
2. Same request with **Demo scenario → D**. Buy is blocked; try Retry, then Change… → 40.
3. Same request, choose *40* and *Subscription*: the terms must be acknowledged before Buy.
4. Tick **Baseline card** and repeat step 1 to see the comparison card.

Files: `app.py` server · `agent.py` task flow · `validator.py` rules R1–R8 · `mock_model.py` simulated model · `mock_shop.py` simulated shop and browser tool · `static/` page · `tests/` · `docs/` diagram, storyboards and screenshots.

## Development record

| Stage | What changed and why | What was checked |
|---|---|---|
| Lab 2 (Oct) | Storyboards from my own experience: an agent picked a large pack with Subscribe & Save. | — |
| Lab 3 SPEC v1 → v2 (Oct) | Walkthrough showed the v1 card asked before paying but hid guesses and the subscription. v2 added the clarification card and rules R1–R8. | Manual walkthroughs of tests A, B and cases C–H. |
| A1 (Oct) | Literature showed agents keep pre-selected options and that users rarely intervene. Focus narrowed to showing *where each choice came from*. | — |
| Prototype plan (13 Nov) | I chose: full SPEC v2 flow, Python server + web page, simulated model, keep a baseline toggle for A3. | Stage 1 skeleton ran; parser tested on the two SPEC requests. |
| Prototype build (25 Nov) | Built the full flow. I chose to expose only case D in the demo menu and put the baseline toggle in the side panel. I kept two choices made during the build: with "You choose" plus a budget, the cheapest offer *within* budget is picked and the cheaper over-budget pack is mentioned; the baseline card never blocks Buy, so A3 can test whether people notice problems from a summary alone. | 18 unit tests pass; headless-browser run of every path with no page errors (screenshots in `docs/screenshots/`). |
| Fix after first run (25 Nov) | In case D the step log said the agent had "switched" the option although the page had not changed. Reworded to "clicked", because the agent cannot know the click worked until read-back. Unit prices rounded to match the shop page. | Re-ran tests and screenshots. |
| Fix after storyboard review (25 Nov) | Building the storyboards showed the clarification card printed "null" once every field was answered, and answered fields still said "Please choose". Fixed both; answered fields now say "your answer". | Re-captured frames; checked the text is gone. |
| Test correction (25 Nov) | A test changed quantity to 2 under "under £5"; the system correctly refused (£7.70), so the test, not the code, was wrong. | Test now uses a no-limit task. |
| My manual check (25 Nov) | I ran all four README scenarios, including the baseline card with case D. Clarification blocking, the case D block and change, subscription acknowledgement and the baseline's Buy all behaved as expected. I found six problems: R2 missing from "What I checked"; O2 shown as 9.63p in the shop but 9.62p on the card; the baseline card in case D showing the £6.84 subscription total with the one-time 9.00p unit price, while the step log still showed a red ✗; run-log entries cut off at about 140 characters; no feedback in the card after Retry; and the subscription checkbox locking after ticking, with the step log staying on ⏸. | — |
| Fixes from my check (25 Nov) | All six fixed: R2 listed; one half-up rounding function used by both shop and card; baseline unit price taken from the checkout and its step log made neutral; full JSON per log entry; Retry shows the attempt and result; the acknowledgement can be withdrawn, which removes Buy again. | 6 new tests (24 in total); re-checked each fix in the browser. |

## AI assistance

- **ChatGPT** (Lab 3): helped draft SPEC v2 text and diagrams; logged in my Lab 3 prompt log.
- **Claude (Anthropic)**: read the assignment brief and my Lab 3 SPEC, proposed how course concepts map to the design, and wrote the prototype code, tests and a first draft of this README from my decisions. I chose the scope, stack, simulated model, baseline toggle and which failure branch to expose.
- **How the output was checked:** the rules and expected totals were compared with SPEC v2 (e.g. case B must give O3, one-time, £7.20; £5 must fail "under £5"). Problems found in review were fixed, including six I found by running every scenario myself (see the development record).

## Additional files

- `docs/system-diagram.png`: components, flows, and implemented / simulated / planned labels.
- `docs/storyboard-*.png`: the three interactions used in the report.
- No ZIP file.
