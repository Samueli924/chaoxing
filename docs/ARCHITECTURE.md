# Architecture

`main.py` reads configuration, selects courses and schedules chapter jobs. Chapter requests are handled by `api/base.py`; parsers in `api/decode.py` separate HTML/JSON decoding from requests. Question providers in `api/answer.py` support the configured answer service.

Task Center is a separate phase. `api/task_center.py` reads teaching tasks and processes unlocked groups sequentially. Chapter plans reuse chapter processing and synchronize the platform-provided completion information. Video and document requests respect real duration requirements. Failed, unsupported and locked plans remain unfinished; a Task Center failure does not stop chapter processing.

`api/ai_writer.py` validates generated substantive text before use. `api/review.py` writes a durable pending record before sending and appends outcome events. Choice and judgment answers appear in runtime traces, without creating substantive-text review records.

`api/paths.py` manages local user data; `api/cookies.py` isolates saved sessions by account. `api/privacy.py` redacts secrets before messages reach console and file sinks.

Tests use standard-library `unittest`, fake HTTP sessions and temporary data directories. They do not need credentials or network access. Platform acceptance and offline correctness are separate claims.
