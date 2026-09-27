# Project State

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
