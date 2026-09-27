# Connection repair and course acceptance (in progress)

The local environment's Python socket connect intermittently raises EBADF before sending a request, including on unrelated public HTTPS sites. System curl reaches the same sites. The OS-level cause remains unproven.

`CHAOXING_HTTP_TRANSPORT` supports `auto` (default), `requests`, and `curl`. Auto switches only when the exception chain proves an EBADF while opening a connection; it does not replay timeouts, read failures or ambiguous failed submissions. The fallback uses the installed curl executable, verified TLS and bounded timeouts. Requests retains cookie scope and redirect handling. Credentials, query parameters and bodies are passed through stdin, never command arguments or temporary files. It supports buffered HTTP(S) and UTF-8 form/JSON requests, not streaming uploads/downloads. Response errors expose exit codes instead of private URLs.

References: [curl configuration and transport options](https://curl.se/docs/manpage.html), [Requests transport adapters](https://requests.readthedocs.io/en/latest/user/advanced/#transport-adapters).

Video execution now begins at the server's recorded resume position instead of reporting completion immediately. It uses a monotonic clock and 30-second media progress intervals. A rejected initial report stops execution. Stopping may leave the final interval unsaved; fresh server readback is required.

Verified on 2026-09-27 UTC:
- Password login using the existing local env, authenticated course list and chapter/card reads.
- Actual `scripts/local.py --check` entry point with default auto fallback: 8/8 checks passed.
- A 70-second 1x resume test stopped at 70.00 seconds. Progress reports 822, 852 and 883 returned HTTP 200. Immediate fresh card readback advanced from 822 to 852 seconds; course completed-task count remained 1/118.
- 13 focused transport/resume tests passed (real loopback HTTP, repeated cookies, redirects, UTF-8 payloads, gzip, secret-free argv, error handling and correct resumed progress).
- Full selected-course inventory: 69 chapters; 60 video tasks; 58 chapter tests; 3 document and 1 reading attachments without task flags. Initially only one task was complete. No inventory errors.

**Full course acceptance has not passed.** Every remaining task must complete and be checked against both server cards and 118/118 aggregate progress. A pre-completed other course is not evidence that this run completed the target. Non-task attachments must also be checked. Scores and actual task completion are separate checks.
