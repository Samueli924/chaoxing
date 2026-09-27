# Connection repair and course acceptance

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

**Historical checkpoint: full course acceptance had not yet passed.** Every remaining task must complete and be checked against both server cards and 118/118 aggregate progress. A pre-completed other course is not evidence that this run completed the target. Non-task attachments must also be checked. Scores and actual task completion are separate checks.

## Full-course test found a second video defect

Normal Brave traffic and its current public player script identify events as playing=0, drag=1, pause=2, play=3, ended=4. The legacy runner repeatedly sent play=3 as a heartbeat, so HTTP 200 and an end-position bookmark did not establish completion. The runner now sends play=3 once, periodic playing=0, and ended=4 only after reaching the end through elapsed playback. An unfinished end-position bookmark restarts from zero instead of repeatedly asserting completion.

Evidence source: the course-loaded `https://mooc1.chaoxing.com/ananas/videojs-ext/videojs-ext.min.js?v=2026-0902-1207` (static inspection only) plus actual normal play/pause/heartbeat requests in the authorized Brave tab. The browser also states that at least 90% viewing duration is required.

A previously unplayed 220-second video was then run at 1x. Its progress response changed to isPassed=true, and a fresh task card independently confirmed isPassed=true with no pending job flag. This confirms one complete video transaction, not full-course acceptance.

All 112 regression tests passed after the event repair. Course tests are being submitted from a local curated bank; every result is checked against the actual server task flag and score. Wrong answers are recorded separately for correction; submission success alone is not a correctness claim. Three non-task PDF files returned HTTP 200, valid PDF signatures and page counts 2, 13 and 16.

## Serial continuation evidence

The event repair is published as `0368d511b74a0798cc6ebbfa0652f24b7f760b85`; its [CI run 36292698195](https://github.com/ieduer/chaoxing/actions/runs/36292698195) passed. At that historical checkpoint, the existing batch was the sole video worker batch, with four workers at 1x and a finite 12-hour deadline.

A fresh independent inventory read all 69 chapters without error and reconciled 60 video, 58 test, 3 document and 1 reading attachments. No tests remained in the pending-job list. Of 57 new submissions, 54 were full marks; three independently reread grades remain 80, 80 and 75. Their result pages have no normal redo control, and the attempted retake returned `WorkRedoUnavailable`. Corrected local bank entries do not constitute corrected submissions.

The browser video excluded from the batch reached 994.645/994.645 seconds at normal speed and displayed its completed-task indicator. The non-task book opened through the course UI and loaded an actual substantive chapter. The task-created reader tab was closed and earlier network-event capture disabled; the user's original course tab remains open.

Completed test attachments omit the pending `job` flag and do not necessarily carry `isPassed`; the final audit therefore must verify each graded result page as well as the card and aggregate progress. Video completion uses its positive `isPassed` evidence. The in-flight inventory is non-atomic because the batch continues to finish tasks. Final acceptance requires a fresh stable read after the batch ends, with 118/118, 60 confirmed videos, 58 submitted results and no pending jobs. At that historical checkpoint this gate had not yet passed; the final gate below supersedes that state.

## Final independent acceptance — 2026-09-27 UTC

**Passed: 118/118 task points, zero pending jobs and zero reconciliation errors.** After every playback worker exited, independent reads of all 69 chapter cards found 60 positively completed videos and matched all 58 completed tests to the same-course graded-result audit (less than one hour old). Aggregate progress was stable at 118/118 before and after the read. All 58 grades were verified: 55 scored 100, two scored 80 and one scored 75. The three non-perfect tests expose no normal redo entry; no corrected resubmission is claimed.

The formal read-only entry point `scripts/local.py --verify --use-cookies` independently exited 0, reported server verification passed and returned 118/118 with zero pending. The verified implementation is `6d14f8bb5ee3ef618e617285607594d26841a085`; six runtime source hashes are retained privately. Its [CI 36298930480](https://github.com/ieduer/chaoxing/actions/runs/36298930480) passed, with 150 offline regression tests. Subsequent acceptance-document changes do not change that runtime.

All three non-task PDFs were independently read (HTTP 200, valid PDF signatures, 2/13/16 pages); the non-task book opened through the normal course UI and loaded a substantive chapter. This establishes platform completion and resource access, not learning quality or perfect grades.

The final 12-worker batch used the platform's native 60-second request-start reporting cadence and mandatory 1x speed. It confirmed 25 videos from 92/118; one separately repaired video completed after 124.04 seconds of bounded supplemental playback. The batch's exit 1 preserves that historical failed attempt even though its final server verification passed. Both independent final gates above also passed; no batch was restarted. The 16-worker profile encountered an unconfirmed end and was rejected. Twelve workers are a tested practical profile, not a universal optimum. The supplemental method was live-tested separately; the automatic transition in the final implementation has regression coverage, not a separate live reproduction.

Private receipts: `reconciliation-final.json`, `official-verify-final.json`, `reconciliation-grades.json`, `cadence-completed.json` and `partial-repair.json` under the owner's private acceptance directory. Raw questions, account identifiers and credentials are not published. Notifications and paid providers remained disabled. The original user-owned Brave tab was preserved; task-created reader tab and network capture were already closed.

## Final hardening readback

At 2026-09-27 06:55:46 UTC, after concurrency downshift, native maximum-speed defaults and media error-budget hardening, `scripts/local.py --verify --use-cookies` again exited 0 with 118/118 and zero pending. Private source hashes bind this result to the six relevant runtime files. No playback, quiz submission, external provider or notification was used. 160 offline tests passed; adaptive concurrency was tested with controlled concurrent failures, not by intentionally disrupting the live platform. See README for defaults, failure handling and limits.
