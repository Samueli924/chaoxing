# Chaoxing Course Automation (CLI)

**English** | [中文](README.zh-CN.md)

[![CI](https://github.com/Samueli924/chaoxing/actions/workflows/tests.yml/badge.svg)](https://github.com/Samueli924/chaoxing/actions/workflows/tests.yml)
[![Release](https://img.shields.io/github/v/release/Samueli924/chaoxing?include_prereleases)](https://github.com/Samueli924/chaoxing/releases)
[![Last commit](https://img.shields.io/github/last-commit/Samueli924/chaoxing)](https://github.com/Samueli924/chaoxing/commits/main)
[![License](https://img.shields.io/github/license/Samueli924/chaoxing)](LICENSE)

A command-line tool that studies Chaoxing (Xuexitong / Fanya) courses without opening a browser. It covers both entries the platform has: **Chapters** (the table of contents) and the **Task Center · Teaching Tasks**.


> **Coverage.** Chapter task types and Task Center videos, chapter sync, think-ladder practice, homework and discussions are implemented. Duration-only documents, situational dialogue, thinking questions and classroom activities require manual completion.
>
> Completion always comes from the platform's own status re-check — the tool never reports a task as finished because it pressed submit.

Console samples in this document are translated from the Chinese output the CLI prints.

## Coverage

| Entry | Status | Covers |
| --- | :---: | --- |
| **Chapters** (table of contents) | ✅ | Every task point: video, document, reading, chapter quiz, live |
| **Task Center · Teaching Tasks** | 🟡 | The types below |

| Task type | Status | How it is handled |
| --- | :---: | --- |
| Video | ✅ | Played through the task engine at the real playback pace |
| Chapter sync | ✅ | Runs chapter automation, then calls the platform's chapter-score sync |
| AI practice | 🟡 | The thinking-ladder type: dialogue over `main-talk` SSE, then the end-report call that makes the platform score it. The newer situational-dialogue type is a different API and is not adapted |
| Homework | ✅ | Multiple choice / true-false / fill-in through the question bank or AI; short answers written by `api/ai_writer.py` |
| Topic discussion | ✅ | Reads existing replies for style, writes a non-duplicate reply, submits it |
| Document | ⚠️ | Documents use 30-second reporting and platform status checks. Duration-only requirements remain unsupported; attempts are limited to once per 24 hours |
| Thinking questions | ❌ | Not supported — the tool says so and leaves them to you |
| Classroom activities / check-in | ❌ | Not supported |

## What it does not do

- **It never fakes completion.** A task counts as done only after the platform's status re-check.
- **It never speeds up watch time.** Videos with a duration requirement play at 1x; documents are reported on a 30-second cadence.
- **It does not skip the unlock order.** Task Center groups unlock in order, and the tool re-reads group state instead of jumping ahead.
- **It does not run anywhere but your machine.** No hosted service, no telemetry, and it talks only to Chaoxing and the answering provider you configure.
- **It does not handle thinking questions, classroom activities or check-in.**

## Requirements

- Python 3.13 or newer (tested on 3.13 and 3.14)
- macOS, Linux or Windows. `./cx` needs Bash; on Windows run `python setup_wizard.py`
- Dependencies: `python -m pip install -r requirements.txt` (requests, beautifulsoup4, loguru, tqdm, openai, ddddocr, ...)
- Optional: a DeepSeek API key for AI answering, a question-bank token, or a push service

## Quick start

### 1. Install Python 3.13 or newer

Download it from [python.org](https://www.python.org/downloads/) and run the installer. On Windows, tick **Add python.exe to PATH**.

### 2. Download the project

```bash
git clone https://github.com/Samueli924/chaoxing.git
cd chaoxing
python -m pip install -r requirements.txt
```

On macOS / Linux, use `python3` if `python` is not found.

### 3. Run the wizard

macOS / Linux:

```bash
./cx
```

Windows:

```powershell
python setup_wizard.py
```

The wizard asks one question at a time: which account (add one the first time) → log in → what to study → how to handle discussions → which courses → how many task points per course → confirm.

Run `./cx` again to reuse the saved setup. `cx setup` changes the answering mode or notifications; `cx --yes` skips the final confirmation.

> **Time is real.** A course with hours of video takes hours. Leave it running; the optional notifications can tell you when it finishes.

> **AI answering uses the DeepSeek API** and may cost a small amount per course. Question-bank services, manual answering and skipping quizzes are also available — see [Answering](#answering).

<details>
<summary>Other ways to run</summary>

```bash
python main.py -c config.ini                        # use ~/.chaoxing/config.ini
python main.py -u <phone> -p <password> -l <ids>    # explicit account and courses
```

The wizard writes `~/.chaoxing/config.ini` for you; `config_template.ini` documents every option.

</details>

## Use

| Command | What it does |
| --- | --- |
| `./cx` | Interactive wizard (recommended) |
| `cx setup` | Change the answering mode or notifications |
| `cx discuss` | Browse the discussion board and reply to the threads you pick (`--list-topics` lists only) |
| `cx review` | Read the AI-written text that was submitted (`--days N`, `--all`, `--list`) |
| `cx --yes` | Same as `./cx`, without the final confirmation |
| `python main.py -c config.ini` | Run from `~/.chaoxing/config.ini` |
| `python main.py -u <phone> -p <password> -l <ids>` | Explicit account and courses. Avoid `-p` in a shared terminal — it lands in your shell history |

A pre-run scan runs before every course and prints what is left. It only reads, and a scan failure never blocks the run.

```text
  Pre-run scan
  ----------------------------------------------
  Example Course
    Chapters   139 sections - 37 done - 102 left, resuming at 1.1 Course intro
    Tasks      9 teaching tasks - 77 task points (62 done - 9 pending - 6 locked)
    Pending    homework 1 - topic discussion 1 - video 2 - document 3 - AI practice 2
  ----------------------------------------------
```

### Numbers and scope

A number you type is **how many unfinished task points to do in this run**. Finished ones are always skipped, and `all` or Enter means everything still unfinished. Chapters and teaching tasks are counted separately.

| Scope | What runs |
| --- | --- |
| Chapters + Task Center | Both entries (recommended) |
| Chapters only | Chapters |
| Task Center only | Teaching tasks |
| Discussions only | Discussions; everything else is skipped this run. Also `--only-discussion` |

Topic discussions belong to the Task Center, so the first and third scope include them.

### Discussions

| Mode | Entry | What it does |
| --- | --- | --- |
| Automatic task discussions | part of the Task Center | Walks the discussion task points in the course's required order, reads the existing replies, writes one ordinary reply and submits it |
| Discussion board | wizard choice, or `./cx discuss` | Lists the board, you pick threads (`1,3,5` / `1-3` / `all`), each one shows a draft and asks `y/n` before sending |

Both modes read existing replies, validate the draft, display it and save it under `~/.chaoxing/reviews/` before submitting. Discussion-board replies always require individual confirmation; `--yes` does not bypass it. Task discussions follow `task_center_submit_mode`: `confirm` asks before sending, while `auto` sends after validation and recording. The client checks existing replies to avoid duplicates.

### Answering

| Wizard choice | Config `provider` | Notes |
| --- | --- | --- |
| DeepSeek AI | `AI` | Recommended. Needs a DeepSeek API key |
| Question bank | `TikuYanxi` | Needs a token from the provider |
| Question bank (GO) | `TikuGo` | Optional authorization |
| Question bank + AI fallback | `TikuYanxi,AI` | More accurate; still needs the token |
| Question bank (GO) + AI fallback | `TikuGo,AI` | More accurate |
| Manual | `TikuManual` | You type every answer |
| Do not answer | *(empty)* | Quizzes are skipped, which can block chapter unlocking |

Objective answers are submitted as option letters or true/false only, never as explanatory sentences. Short answers and discussion replies are written by `api/ai_writer.py`.

### Submitting

`task_center_submit_mode = auto` (the default) answers and submits in the background; `confirm` shows a preview and asks before every submission. Set it in the config or with `--task-center-submit-mode`. Either way, completion still comes from the platform's status re-check.

### Notifications (optional)

Bark, ServerChan, Telegram or Qmsg. Leave `[notification] provider` empty to disable. Messages are sent when a run starts, finishes, is interrupted or errors.

### Configuration

The wizard writes `~/.chaoxing/config.ini`; `config_template.ini` documents every key. The common ones:

| Key | Default | Meaning |
| --- | --- | --- |
| `chapter_study` | `true` | Study chapters |
| `task_center` | `true` | Study Task Center teaching tasks |
| `only_discussion` | `false` | Study discussions only |
| `discussion_mode` | `task` | `task` = automatic task discussions; `board` = pick threads on the board |
| `jobs` | `2` | Task points processed in parallel |
| `speed` | `2` | Video speed (watch-duration videos always run at 1x) |
| `max_points_per_course` | *(empty)* | Unfinished chapter task points per course |
| `max_tasks_per_course` | *(empty)* | Unfinished teaching tasks per course |
| `task_center_submit_mode` | `auto` | `auto` or `confirm` |
| `serial_video` | `false` | One video at a time, if the platform rolls progress back |
| `ai_practice_min_score` | `85` | Target score for AI practice |
| `ai_practice_max_rounds` | `5` | Retries for AI practice |

## Reviewing AI-written text

Every substantive text an AI wrote and the tool submitted — quiz short answers, homework essays, discussion replies, AI-practice answers — is printed while the run is going and saved to disk:

```text
~/.chaoxing/reviews/YYYY-MM-DD.md     # one Markdown file per day
~/.chaoxing/reviews/index.jsonl       # index used by cx review
```

| Command | Shows |
| --- | --- |
| `./cx review` | Today's items; type a number to read the full text |
| `./cx review --days 7` | The last 7 days |
| `./cx review --all` | Everything recorded |
| `./cx review --list` | The list only |

Objective answers (letters, true/false) are not recorded — there is nothing to review. The records never contain passwords, cookies or tokens.

## Data and privacy

```text
~/.chaoxing/
  config.ini        # your settings
  accounts/         # per-phone credentials, cookies and run configs
  cache.json        # answer cache
  reviews/          # AI-written text kept for review
  submissions.json  # local ledger, avoids duplicate homework submissions
  chaoxing.log      # run log (DEBUG; CX_LOG_LEVEL=TRACE for more detail)
```

- Nothing in this directory is committed to the repository. It is created with directory mode `0700` and file mode `0600`.
- Each phone number keeps its own credentials and cookies, so accounts never overwrite each other.
- The tool talks only to Chaoxing and the answering provider you configure. There is no telemetry and no upload of course content.
- Login captchas are recognised locally with OCR; nothing is sent to a third-party service.
- Use it only with an account you own, and follow your school's rules.

## Troubleshooting

| Problem | What to do |
| --- | --- |
| Login captcha keeps failing | Run `./cx` again; the tool backs off for 60 seconds after repeated failures. If it still fails, log in once in a browser |
| A Task Center group never unlocks | Groups unlock in order and the platform syncs with a delay; re-run later |
| Thinking questions are skipped | Not supported — finish them manually |
| A document task stays incomplete | Known gap: duration-only documents were not counted by the platform. The tool never marks it complete, and skips re-reading the same document for 24 h |
| AI practice scores below the pass line | The platform grades the practice itself. The tool answers with a reasoning model and majority voting, and retries within the configured rounds |
| AI answering fails or the key is rejected | Check the key and balance. With a fallback chain (`TikuYanxi,AI`) the next provider is tried; otherwise the quiz is skipped |
| Where is the log? | `~/.chaoxing/chaoxing.log`. When filing an issue, attach a sanitized excerpt only — it contains account identifiers |
| How do I stop it? | Press `q` or `Ctrl+C`. Work already reported to the platform is kept; re-running picks up from the platform's own progress |
| Can I close the terminal? | No — videos only progress while it runs. Use `tmux`, `screen` or `nohup` to keep it alive |
| Will re-running redo finished tasks? | No. The platform state is read first and completed points are skipped |
| Cookies expired | Run `./cx` and log in again; the per-account cookie file is refreshed automatically |
| `pip install` fails on `lxml` / `ddddocr` | Use a fresh virtual environment: `python -m venv .venv && .venv/bin/pip install -r requirements.txt` |
| `./cx: Permission denied` | `chmod +x cx` once, or run `python setup_wizard.py` on Windows |

## Development

```bash
make test      # offline unit tests (335 tests, no network, no real account)
make lint      # compile check + tests — run before every commit
make test-313  # the same suite on the CI version (3.13); local Python may be 3.14
make doctor    # environment self-check
```

Tests use the standard library `unittest` against fakes (`FakeSession`, `FakeTC`) — no pytest, no ruff, no network. CI ([.github/workflows/tests.yml](.github/workflows/tests.yml)) runs them on Python 3.13 for every push and pull request.


| Path | Purpose |
| --- | --- |
| `cx` | Launcher: `./cx`, `cx setup`, `cx discuss`, `cx review`, `cx --yes` |
| `setup_wizard.py` | Interactive setup and study wizard |
| `main.py` | CLI entry, chapter task queue and Task Center orchestration |
| `api/base.py` | Chaoxing core: login and chapter task points |
| `api/task_center.py` | Task Center client: groups, task points, video and document reporting |
| `api/discussion.py` | Discussion board: thread list, board resolution, pick-and-reply |
| `api/scan.py` | Pre-run scan |
| `api/review.py` | Review log for AI-written text |
| `api/answer.py` | Question banks (including AI providers) and answering |
| `api/ai_writer.py` | Human-like writing for homework and discussions |
| `tests/` | Offline unit tests |
| `docs/` | Handoff notes, runbook, architecture, capture samples |

## Repository policy

- Issues and pull requests are welcome; keep each change small and focused.
- Never commit credentials, cookies, tokens or personal data. Samples must be sanitized.

## References

- Upstream project: [Samueli924/chaoxing](https://github.com/Samueli924/chaoxing)

## License

GPL-3.0 — see [LICENSE](LICENSE). For learning and personal use only; do not use it on accounts you do not own. You are responsible for following your school's rules and the platform's terms of service.
