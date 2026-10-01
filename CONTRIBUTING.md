# Contributing

Open a focused pull request against the current upstream `main`. Describe the concrete problem, resulting behavior and verification. Keep the existing license and author attribution. Maintainers decide which changes to merge and release.

Behavior changes need offline `unittest` regression coverage. Tests use synthetic data and fake requests, never real credentials or course submissions. Run `make lint` and the suite on Python 3.13. Confirm installation and entry points when changing packaging.

Public files contain source, synthetic tests, configuration examples and user or maintenance documentation. Private agent notes, task boards, session logs, development progress, experiments, captures and audit reports belong outside Git. Run `python tools/audit/publication_guard.py` before publishing.

Never commit or log credentials, cookies, service keys or identity parameters. Generated substantive text must pass validation and be recorded before requests, with honest outcome states; objective letters belong in runtime traces only. Failed recording or validation blocks the affected submission.

Respect real study duration, sequential group unlocks and request pacing. Never count an unsupported, skipped or unconfirmed task as complete. Preserve existing upstream behavior and regression coverage. Prefer one feature per pull request and disclose any dependency on another contribution.
