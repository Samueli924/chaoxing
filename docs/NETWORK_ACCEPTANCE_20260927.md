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

## Full-course test found a second video defect

Normal Brave traffic and its current public player script identify events as playing=0, drag=1, pause=2, play=3, ended=4. The legacy runner repeatedly sent play=3 as a heartbeat, so HTTP 200 and an end-position bookmark did not establish completion. The runner now sends play=3 once, periodic playing=0, and ended=4 only after reaching the end through elapsed playback. An unfinished end-position bookmark restarts from zero instead of repeatedly asserting completion.

Evidence source: the course-loaded `https://mooc1.chaoxing.com/ananas/videojs-ext/videojs-ext.min.js?v=2026-0902-1207` (static inspection only) plus actual normal play/pause/heartbeat requests in the authorized Brave tab. The browser also states that at least 90% viewing duration is required.

A previously unplayed 220-second video was then run at 1x. Its progress response changed to isPassed=true, and a fresh task card independently confirmed isPassed=true with no pending job flag. This confirms one complete video transaction, not full-course acceptance.

All 112 regression tests passed after the event repair. Course tests are being submitted from a local curated bank; every result is checked against the actual server task flag and score. Wrong answers are recorded separately for correction; submission success alone is not a correctness claim. Three non-task PDF files returned HTTP 200, valid PDF signatures and page counts 2, 13 and 16.

## Serial continuation evidence

The event repair is published as `0368d511b74a0798cc6ebbfa0652f24b7f760b85`; its [CI run 36292698195](https://github.com/ieduer/chaoxing/actions/runs/36292698195) passed. The existing batch remains the sole video worker batch, with four workers at 1x and a finite 12-hour deadline.

A fresh independent inventory read all 69 chapters without error and reconciled 60 video, 58 test, 3 document and 1 reading attachments. No tests remained in the pending-job list. Of 57 new submissions, 54 were full marks; three independently reread grades remain 80, 80 and 75. Their result pages have no normal redo control, and the attempted retake returned `WorkRedoUnavailable`. Corrected local bank entries do not constitute corrected submissions.

The browser video excluded from the batch reached 994.645/994.645 seconds at normal speed and displayed its completed-task indicator. The non-task book opened through the course UI and loaded an actual substantive chapter. The task-created reader tab was closed and earlier network-event capture disabled; the user's original course tab remains open.

Completed test attachments omit the pending `job` flag and do not necessarily carry `isPassed`; the final audit therefore must verify each graded result page as well as the card and aggregate progress. Video completion uses its positive `isPassed` evidence. The in-flight inventory is non-atomic because the batch continues to finish tasks. Final acceptance requires a fresh stable read after the batch ends, with 118/118, 60 confirmed videos, 58 submitted results and no pending jobs. This gate has not yet passed.
