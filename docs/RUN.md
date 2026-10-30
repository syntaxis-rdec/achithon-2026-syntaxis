# Running AGENTGATE

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

macOS / Linux:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Tests:

```bash
pytest
```

Demo state lives in `data/agentgate.sqlite`. Use **Reset demo data** in the dashboard to start clean.

## What to try in the dashboard

1. Actor `agent-assistant (AI)`, tool `read_document`, document `doc-003` (the one containing an
   injected "ignore all policies" instruction) → **BLOCKED**, no document text opened.
2. Actor `analyst`, tool `save_report`, sources `doc-004` + `doc-001` → allowed, report inherits
   `CONFIDENTIAL` and keeps both provenance ids.
3. Actor `analyst`, tool `deliver_inbox`, that report, recipient `team@corp.example` → **BLOCKED**,
   recipient clearance too low. Delivered messages stays 0.
4. Same report to `manager@corp.example` → allowed, one message in the mock inbox.
5. Actor `agent-assistant`, deliver the confidential report to `manager@corp.example` → **BLOCKED**
   after **Reload state from disk**, proving the label survived a fresh session.
