# AGENTGATE Web Interface (Aryan Lane)

This is the lightweight Flask presentation layer for AGENTGATE.

## Run instructions

```bash
python web/app.py
```

Then open `http://127.0.0.1:5000` in your web browser.

## Features

- **Activity Overview**: High-level security metrics, protected tool count, and quick review status.
- **Protected Tools**: Independent permission boundaries for document reading, reporting, and inbox delivery.
- **Authorization Requests**: Human-in-the-loop review interface for sensitive actions.
- **Resumable Workflows**: Visual tracking of workflow progress and step status.
- **Audit Trail**: Searchable, tamper-evident log of security decisions with plain-English reasons.
- **Workspace Settings**: Demo configuration and policy toggles.
