# Project State

Last updated: 2026-09-27 UTC
Canonical source: https://github.com/ieduer/chaoxing main; checkout /Users/ylsuen/chaoxing/chaoxing.

## Objective and acceptance

Complete and independently reconcile every element of one initially incomplete course: 69 chapters, 118 task points (60 videos and 58 chapter tests), plus 3 non-task PDFs and 1 reading resource. The initial target baseline was 1/118. The other, already-complete course is not acceptance evidence. **Full-course acceptance remains pending.**

## Published implementation and checks

- Consolidation: `6ae9936`; connection/resume repair: `cb7054a`; actual player event repair: `0368d511b74a0798cc6ebbfa0652f24b7f760b85`.
- All 112 offline regression tests passed on the event repair. Its GitHub CI run [36292698195](https://github.com/ieduer/chaoxing/actions/runs/36292698195) also passed.
- Local env password login, authenticated course listing and task-card reads succeeded. The formal local launcher selfcheck passed 8/8 using the default auto transport.
- Auto transport only falls back for a proven pre-send EBADF connection failure. The OS cause remains unproven. Video events now match the observed platform player: play=3, playing=0, ended=4; progress advances through elapsed monotonic time.

## Efficiency revision

148 offline regressions passed for bounded media requests/end confirmation, preserved bookmarks, no automatic whole-media replay, platform speed restrictions, independent per-video card confirmation and final course verification. `--verify` is read-only and returns nonzero on incomplete or unverifiable progress. The original process exited before a recorded serial handover. Revision `08af3f5` passed CI 36296106139 and resumed at 77/118 through the canonical Runner with eight workers. A distinct native-cadence probe independently completed a previously unstarted 382-second video with seven reports in 381.36 seconds. The native 60-second cadence now follows the actual task-card setting; the 16-worker comparison confirmed six additional videos but encountered one unconfirmed end and stopped. Fresh progress is 92/118. That profile is not accepted as stable. A revised request-start cadence and bounded 12-worker comparison follow; ordinary media failures are isolated without automatic replay. [Video comparison and measurement plan](docs/VIDEO_EFFICIENCY.md).

## Live evidence and limits

- 57 previously pending tests were submitted and independently confirmed; 54 scored 100, two scored 80 and one scored 75. One test was already complete. A fresh inventory of all 69 chapters found no pending test jobs.
- The three non-perfect results were independently reread as 80, 80 and 75. Their result pages expose no redo control; the attempted normal retake returned `WorkRedoUnavailable`. Corrections are retained only in the private local bank, and are not claimed as successful resubmissions.
- One previously unplayed 220-second video completed through the runner and a fresh card confirmed completion. The excluded browser video reached its actual 994.645-second end at 1x and displayed the completed-task indicator.
- The original four-worker batch was stopped only after preserving its checkpoint and verifying process exit. The eight-worker continuation has independently confirmed eight additional videos with no failed tasks at its recorded 930-second checkpoint. Preserve current server progress during any serial handover; never start overlapping copies of the same job. See the private handoff for current process ownership.
- All 3 PDFs returned HTTP 200 with valid signatures and page counts of 2, 13 and 16. The reading resource opened from the course and loaded a substantive chapter in the normal Brave reader.
- The final gate is a stable, fresh 118/118 aggregate, all 60 completed video cards, all 58 submitted-result pages, zero pending jobs and the four non-task resource checks. A running snapshot is not a final reconciliation.

## Privacy, ownership and rollback

Private evidence and handoff: `/Users/ylsuen/CF/reports/private/chaoxing-acceptance-20260927/`. Runtime: `/private/tmp/cf-task-chaoxing-live-acceptance-20260927`; its manifest is under CF private runtime-artifact-manifests. Preserve runtime files while the existing worker is active. Retained local banks are in Git-ignored `data/acceptance-20260927`; do not publish questions, account identifiers, credentials, cookies or raw network evidence.

Notifications and paid providers remain disabled. Multi-account operation, OCR, notifications, native packages and optional browser userscript installation have not received live acceptance. Details: [network acceptance](docs/NETWORK_ACCEPTANCE_20260927.md) and [integration record](docs/INTEGRATION.md).

Rollback code with a normal reviewed revert; `6ae9936` is the pre-transport anchor. Original source/history remains under `.git/chaoxing-recovery-20260927`, `master` and `legacy-closty`. Git rollback cannot undo already-submitted learning activity.
