# Project State

## Current status — 2026-10-08 15:18 UTC

**Historical completion is not accepted as current evidence.** Later authenticated readback contradicted the dated acceptance. The underlying cause has not been established. Do not treat the previous concurrency profile as proof of durable acceptance, or replay an entire course merely to conceal a mismatch. Reconcile the same account/course/task with current native records first. Account-specific diagnostic evidence is retained privately and excluded from this public repository.

The original receipts below are historical and establish only their dated observations. Immediate task-card and aggregate confirmation cannot guarantee later platform state. No runtime fix for the underlying regression is claimed.

Resource completion hardening: document/read completion now requires HTTP 200 and an explicit positive status. An ambiguous response, timeout or access failure is terminal for the attempt: no HTTP-adapter retry, fallback endpoint replay or whole-chapter replay. Only 404/405 allows the compatibility endpoint. Cancellation is checked before sending; error logs exclude raw response and exception text. These failures still downshift subsequent concurrency. 92 focused tests passed, including a real-thread no-requeue/downshift test and rejected work-submit/redo responses. Quiz submission and redo now share strict positive-status validation; redo HTTP errors are rejected, redo GET transport retries are disabled, and failed work submissions cannot be replayed by whole-chapter retries. Native reference-resource access was checked separately; non-task resources do not establish live acceptance of document/read completion endpoints. These endpoint hardening claims remain distinct from the course acceptance below.

## Current bounded acceptance — 2026-10-08

With explicit authorization, one remaining-task batch completed 58 videos and 30 quizzes without failed or cancelled jobs. Existing completed tasks were preserved. Twelve workers were used; the course enforced 1x. All 814 media reports returned HTTP 200; no live error downshift occurred, so downshift remains covered by fault-injection tests.

The first full readback at 15:14 UTC showed complete aggregate progress but one pending video card; acceptance correctly remained false. No task was replayed. A separate read-only scan ending at 15:18:57 UTC verified all 69 chapters, 118/118 tasks, 60 videos, 58 quizzes, zero pending cards and zero errors. This is an observed synchronization discrepancy, not proof of its cause or a guarantee against later regression. Three reference PDFs and one non-task reader were also checked separately; these are not live tests of document/read completion writes.

The batch loaded `208d3d9602356174d80349fddcadf42a971be45b`; the independent read-only scan used `81168d1d6cfb6053de084628028977e156adee4f`. Later source changes did not hot-reload into the batch. Sanitized per-task receipts and snapshots remain private. The user will arrange subsequent checks; no scheduled monitor was created. Git rollback cannot undo learning activity.

## Historical state — 2026-09-27 (superseded by current status above)

Last updated: 2026-09-27 UTC
Canonical source: https://github.com/ieduer/chaoxing main; checkout /Users/ylsuen/chaoxing/chaoxing.

## Objective

Completed and independently reconciled one initially incomplete course from baseline 1/118: 69 chapters, 60 videos, 58 tests and four non-task resources. The other pre-completed course is not acceptance evidence.

## Accepted result

Independent reconciliation and the formal `scripts/local.py --verify --use-cookies` entry point both passed: stable 118/118, 60 completed videos, 58 graded tests, zero pending/errors. Grades: 55 × 100, 2 × 80, 1 × 75; no normal redo entry exists for the three non-perfect tests. Three PDFs and the book reader were also verified.

Verified runtime: `6d14f8bb5ee3ef618e617285607594d26841a085`; 150 offline tests and [CI 36298930480](https://github.com/ieduer/chaoxing/actions/runs/36298930480) passed. The course enforces 1x. Twelve workers with native 60-second reporting are a tested practical profile, not a universal optimum. Preserve the historical batch failure despite successful bounded repair and final independent gates.

The authoritative final evidence and limits are in [network acceptance](docs/NETWORK_ACCEPTANCE_20260927.md#final-independent-acceptance--2026-09-27-utc); experiment history is in [video efficiency](docs/VIDEO_EFFICIENCY.md).

## Retention and rollback

Private evidence is retained under `/Users/ylsuen/CF/reports/private/chaoxing-acceptance-20260927/`; local banks remain Git-ignored under `data/acceptance-20260927`. Private evidence and scripts were retained with SHA-256 readback; disposable caches and the exact temporary root were removed, and manifest closeout passed. No playback workers remain.

Multi-account operation, OCR, notifications, native packages and optional userscript installation have not received live acceptance. See [integration](docs/INTEGRATION.md) and [network acceptance](docs/NETWORK_ACCEPTANCE_20260927.md). Roll back code through a normal reviewed revert; `6ae9936` is the pre-transport anchor. Preserve `.git/chaoxing-recovery-20260927`, `master` and `legacy-closty`. Git rollback cannot undo submitted learning activity.

## Final hardening and upstream submission — 2026-09-27

The default is now 12 concurrent chapters with automatic error downshift through 8/4/2/1; in-flight work drains before new work starts under the lower limit. Default requested speed is the observed native maximum 2x, capped to 1x unless the task explicitly permits speed changes. Media time budgets, invalid-metadata handling and error classification are strengthened; failed media cannot trigger whole-chapter replay.

160 offline tests passed, including fault-injected real-thread downshift and continuation. Python/JavaScript syntax and diff checks passed. At 06:55:46 UTC the actual local read-only verification entry point again returned exit 0, verified 118/118 and zero pending, with current source hashes retained in private `hardening-readonly.json`. No completed media was replayed. Automatic downshift and unrestricted 2x completion are not claimed as new whole-course live tests. README contains full operational behavior and limits. Submit the verified fork to Samueli924/chaoxing after the canonical push and CI check.
