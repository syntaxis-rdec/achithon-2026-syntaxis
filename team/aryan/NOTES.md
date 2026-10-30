# Aryan — Lane Notes

## Status

Frontend interface implemented in `web/` using Flask and HTML/CSS/JavaScript.

- `web/app.py`: Flask application server.
- `web/templates/index.html`: Dashboard UI with Overview, Tools, Approvals, Workflows, Audit, and Settings.
- `web/README.md`: Run and feature documentation.
- `tests/test_web.py`: Automated tests verifying route availability and required UI panel headings.

## Verification

- `python -m pytest tests/test_web.py`: 2 passed.
- Baseline core tests: all passing.

## Ready to merge

- Branch: `lane/aryan`
- Frontend implementation in `web/` and tests in `tests/test_web.py`.
