# Tanush — demo lane requests

Work on `work/demo` (the stage demo: `docs/DEMO_SCRIPT.md`, `docs/DEMO_RUNSHEET.md`,
`docs/JUDGE_QA.md`, `demo/`, `tests/test_demo_beats.py`). `agentgate/` and `benchmark/*.json` were
treated as frozen; everything below was worked around, not fixed in place. Baseline 67 tests → 83
with the demo suite.

## Requests

1. **`agentgate/store.py` — a `Store` is usable for exactly one script run, and nothing says so.**
   SQLite binds a connection to the thread that opened it. `app.py` used to keep one in
   `st.session_state` via `SessionRegistry`, so a rerun that landed on a different thread died with
   `sqlite3.ProgrammingError` — reproduced, then worked around by building the registry per run.
   Ask: either open with `check_same_thread=False` plus a lock, or say in the docstring that a
   `Store` is single-run. Why it matters beyond the demo: `SessionRegistry`'s stated job ("read
   history survives clicks") is actually done by the `read_history` table, so the cached object was
   never the reason it worked.
   *Workaround now in `app.py`: one `Store` and one registry per run, nothing cached across reruns.*

2. **`agentgate/workflow.py` — there is no way to leave a workflow half-run without crashing.**
   `add_steps` enumerates from 0 and `INSERT OR REPLACE`s, so it rewrites step 0 rather than
   appending. The resumption beat wants "step 0 already done, step 1 still pending under an old
   rulebook", and the only way to get that state is the simulated crash the existing tests use.
   Ask: an append that starts at the current max index.
   *Workaround now in the script: two queued workflows (`DEMO-A`, `DEMO-B`) with identical
   proposals, so the tightened block and the earlier pass are shown side by side instead of one
   workflow being half-run on purpose.*

3. **Recorded defect, deliberately not fixed: "Reset demo data" in `app.py`.**
   On Windows it raises `PermissionError: [WinError 32]` at the `DB.unlink` line because the live
   session still holds the file. Verified in a browser. It fails before erasing anything, so F5
   restores the page and the trail intact. Left alone on purpose: a reset that *worked* would
   delete the staged report and the two queued workflows and leave beats 7–11 with nothing to
   click. The runsheet bans the button and gives the F5 line.
