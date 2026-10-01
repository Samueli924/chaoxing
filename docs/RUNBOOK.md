# Usage and troubleshooting

Use Python 3.13 or newer in a virtual environment and install `requirements.txt`. Run `python main.py --help` for CLI flags. The optional configuration wizard is `python setup_wizard.py`; on macOS/Linux, `./cx` selects the local virtual environment automatically.

User configuration, accounts, cookies, logs and review records live under `~/.chaoxing/`. `CX_DATA_HOME` overrides this directory. Local account files contain credentials and must remain private. Read only your own course data. Optional answer and notification services receive the content needed for their configured functionality.

| Problem | Action |
| --- | --- |
| Login expired | Log in again; do not share cookies or account files |
| A group is locked | Complete the current unlocked group, then allow time for platform status to refresh |
| A request is rejected or captcha appears | Pause and reduce request frequency; repeated retries do not prove completion |
| A video has a watch-duration requirement | Keep real-time playback; a short watch may require replay |
| A document remains unfinished | Do not infer completion from HTTP 200; consult the platform and complete unsupported requirements manually |
| Review storage fails | Fix local permissions or disk space; the affected substantive answer must not be sent |
| An AI answer cannot pass validation | Review the source material or answer manually; rejected output must not be submitted |

`work_redo_enabled` defaults to false. Enable it only for courses allowing repeated submissions. Task Center submission modes are `confirm` and `auto`; the interactive discussion browser still requires explicit confirmation per reply.

Before sharing diagnostics, review them for personal course content. Automatic authentication redaction is a safeguard, not permission to publish full logs. Never attach raw captures or user data to a contribution.
