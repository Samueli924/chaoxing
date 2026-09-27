# Chaoxing project

Canonical repository: https://github.com/ieduer/chaoxing, branch `main`.
Local checkout: `/Users/ylsuen/chaoxing/chaoxing`.
Python CLI and standard-library HTTP console share `api/runner.py`; UI is in `resource/web`.
Use the existing `/Users/ylsuen/.venv/bin/python`. `start.command` loads only CHAOXING_* settings from the local secret file; never commit credentials, cookies, traces or data/.

Run offline checks with `PYTHONDONTWRITEBYTECODE=1 CHAOXING_DATA_DIR=<private-temp-dir> python -m unittest discover -s tests`.
Authenticated tests must distinguish reading pages from running tasks or submitting answers. Notifications require explicit authority; keep them disabled for tests.
Public upstream feature claims are not live verification. Respect actual platform playback and challenge controls. No claim of invisible or risk-free automation.

Local pre-consolidation files are preserved under `.git/chaoxing-recovery-20260927`; old Git history remains on `master` with remote `legacy-closty`. Preserve this recovery source. Read `PROJECT_STATE.md` and `docs/INTEGRATION.md` for current validation and limits.
