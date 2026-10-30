# AGENTGATE demo runsheet

One page. Read it top to bottom once before you go on, and keep it open while you present.

## Pre-flight (10 minutes before)

- [ ] **Power cable in.** Windows drops the frame rate and dims on battery.
- [ ] **Notifications off.** Windows Settings → System → Focus assist → *Alarms only* (or
      *Do not disturb*). Also close Slack/Teams/mail, and quit any screen-recording HUD.
- [ ] **Suite green.** From the worktree root
      `C:\Users\Tanush Garg\Documents\Qoder\2026-10-29\376c904f\team-9-11\.venv\Scripts\python.exe -m pytest`
      → expect **83 passed**. If it is not 83, do not go on; fix or re-read `log.txt`.
- [ ] **Seed, with the server stopped.** `..\.venv\Scripts\python.exe demo\seed.py` (same venv path,
      run from the worktree root). It prints the staged report id, the two workflow ids and
      `inbox: 0 messages delivered`, then asserts its own starting state and exits non-zero if it
      is wrong. Read the two workflow ids — you say them out loud at beats 7 and 9. If a dashboard
      tab is still attached, Windows has the database locked and the seed stops with that
      instruction instead of half-rebuilding: Ctrl-C the server first.
- [ ] **Rulebook is the default one.** The seed prints `rulebook on disk: 12a49fe3ae7fc597`. If it
      prints `c0a7b0e1860531db`, a previous rehearsal left the tightened file in place; the seed
      has now put it back.
- [ ] **Start the app.** `..\.venv\Scripts\python.exe -m streamlit run app.py --server.port 8570`
- [ ] **Port is free and serving.** Open `http://localhost:8570` and see all five sections:
      `1. Propose an action`, `2. Gateway decision`, `3. Audit trail and mock inbox`,
      `4. Evidence — 32 frozen scenarios`, `5. Workflow resumption`. Header caption reads
      `Live · policy fingerprint 12a49fe3ae7fc597`, and section 3 reads
      **Messages actually delivered: 0**.
- [ ] **One browser window, full screen, nothing else open.** Recommended: a single Chrome
      app window — `chrome --app=http://localhost:8570` — F11, no tabs, no address bar, no other
      profile windows.
- [ ] **Zoom for a projector.** Ctrl and `+` twice (125 %). Check at 125 % that you can see
      `Submit to gateway` **and** the red/green decision banner **and** "Messages actually
      delivered" without scrolling. If not, go back to 110 %. You scroll once on purpose, at
      beat 7 — that scroll is part of the timing.
- [ ] **Second window, commands already typed, not running.** Alt-Tab to it at beats 8 and 10 and
      press Enter only:
      ```
      ..\team-9-11\.venv\Scripts\python.exe demo\swap_policy.py tighten      (beat 8)
      ..\team-9-11\.venv\Scripts\python.exe demo\swap_policy.py restore      (beat 10)
      ```
      Both are typed from the worktree root, the same one you seeded from. Put the tighten line in
      the terminal's history first so ↑ ↑ Enter works if you lose the window.
- [ ] **Never touch "Reset demo data"** in section 3. On Windows it raises
      `PermissionError: [WinError 32]` and shows a traceback, because the live session holds the
      file; and even if it worked, the app would not re-create the staged report or the two
      workflows. Recovery is the F5 line below.
- [ ] **Backup recording: NOT MADE.** `docs/PLAN.md` schedules it at T+19:00 and no file exists in
      this branch. Do not imply one. The real fallback is the terminal path at the bottom of this
      page, and it is live, not a recording.
- [ ] **Rehearse the 60-second cut once, in order** — beats 1, 2, 3, 4, 7, 8, 9, 12. Then run
      `pytest -q tests/test_demo_beats.py`; the two rehearsal tests click the same order for you.

## Order of beats

| # | Beat | Click | The one thing that must appear |
|---|---|---|---|
| 1 | Authorized read | `Submit to gateway` (defaults) | `ALLOWED — rule READ-ANALYST` |
| 2 | Labels inherit | `save_report`, `doc-001`+`doc-002`, Submit | `ALLOWED — rule SAVE-ANALYST`, CONFIDENTIAL |
| 3 | Blocked outside | `deliver_inbox`, `vendor@outside.example`, Submit | `BLOCKED before execution — rule RULE-RECIPIENT-NOT-PERMITTED`, delivered **0** |
| 4 | Injection | `agent-assistant`, `read_document`, `agent (AI)`, `doc-003`, Submit | `BLOCKED — rule RULE-READ-CLEARANCE` |
| 5 | Release refused *(extended)* | `analyst`, `Release` | `Refused: not a security officer.` |
| 6 | Officer release *(extended)* | `security-officer`, `Release` | `Created report-… at PUBLIC. Original untouched.` |
| 7 | Permitted run | section 5, `DEMO-A`, `Resume` | `Ran to completion under 12a49fe3ae7fc597`, delivered **1** |
| 8 | Rulebook swap | Enter on `swap_policy.py tighten`, then pick `DEMO-B` | `Rulebook on disk right now: c0a7b0e1860531db`, DEMO-B still 3 × `pending` |
| 9 | Resumption block | `Resume` | `Stopped at the first block under c0a7b0e1860531db`, `done / blocked / halted`, delivered still **1** |
| 10 | Both verdicts *(extended)* | Enter on `… restore`, `Resume` on DEMO-B, scroll to section 3 | `Ran to completion under 12a49fe3ae7fc597`, delivered **2**, two rows for one step with two fingerprints |
| 11 | Finished workflow *(extended)* | `DEMO-A`, `Resume` | "Nothing was re-run", delivered still **2** |
| 12 | Evidence | `Run the suite` | `32/32`, `0`, `0 / 0`, `32/32` |

## Recovery lines

**A step that should block does not block.** Read the header caption. If it still says
`12a49fe3ae7fc597`, the swap never landed: beat 8's Enter did not run, or you clicked Resume
before changing `Saved workflow`. Say "the rulebook on screen is still the old one — that is the
gateway being literal, not being clever", run the tighten command, pick `DEMO-B`, and press
`Resume`. Beat 3 has the same shape: if a delivery you meant to block goes through, the recipient
selectbox is not on `vendor@outside.example` — say so, re-pick it and submit again. A blocked
action that wrongly succeeded is not recoverable inside the 60 seconds: skip to beat 12 and let the
`Unauthorized executions 0` metric carry the claim.

**The app fails to start.** Port busy → use 8571 and say the port out loud. Otherwise it is
normally the wrong working directory: `cd` to `team-9-11-demo`, confirm the venv path exists, and
re-run. If Streamlit itself is broken, do not fight it — `..\.venv\Scripts\python.exe
-m benchmark.runner` prints the same evidence numbers in the terminal in about a second, and
`pytest -q tests/test_demo_beats.py` prints 16 passed. Both are live. Say "the dashboard will not
come up; here is the same gateway from the terminal" and present that.

**The browser dies mid-demo.** The server is still running; the audit trail is in SQLite and is
durable. Reopen `http://localhost:8570` (or F11 / re-focus the app window). You lose the page
state, not the decisions: the trail and the delivered count come back exactly as they were, so
name where you were and continue from the next beat that only reads state. If you were mid-run,
re-run the current beat's click — a delivery is keyed to its workflow step, so a retried step
cannot send a second message.

**"Reset demo data" got clicked, or the state looks wrong.** Do not click it. Tested on Windows:
it raises `PermissionError: [WinError 32]` at `app.py:174` and paints a red traceback on the page,
because the session that is holding `data/agentgate-v3.sqlite` cannot delete it. The good news is
that it fails *before* erasing anything — press **F5** and the page comes back with all five
sections, the same delivered count and the whole trail. So: F5, admit the button is broken on
Windows and that it is off the demo path, and carry on.

Only re-seed when you can stop the server. Windows keeps the file busy while a browser tab is
attached, so `demo\seed.py` stops and says so rather than leaving half-built state. If you
genuinely need a clean board: **Ctrl-C** in the streamlit window → **↑ Enter** on the
`demo\seed.py` line → **↑ Enter** on the streamlit line → **F5** in the tab. About twenty seconds,
back to beat 1 with a clean trail. Say "restarting the demo database" while you do it, then take
the question you were interrupted for. If a judge is mid-question and you cannot restart, don't:
answer from the trail you can already see.

**The swap command fails.** Missing `demo/policies_tight.json` or an identical fingerprint means
you are in the wrong directory — `cd` to the worktree root and re-run. If it still fails, skip
beats 8 and 9 and go straight to beat 12; the resumption behaviour is still readable in the audit
table from beat 7.

**Something on screen contradicts the script.** Do not improvise a defence. Read the reason line
aloud — it is written to be read — and say "the gateway prints why, so I am not guessing either".
Then jump to beat 12.

## After the demo

- [ ] `..\.venv\Scripts\python.exe demo\swap_policy.py restore` if you did not reach beat 10.
- [ ] `git status --short` — clicking `Run the suite` rewrites `benchmark/results.json` with fresh
      random artifact ids inside the `reason` strings. That file is frozen: `git checkout --
      benchmark/results.json`. `data/agentgate-v3.sqlite` and `data/demo_seed.json` are ignored.
- [ ] Append your turn to `log.txt`.
