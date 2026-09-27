# Video efficiency: acceptance before throughput

As of 2026-09-27, the course is still in progress. No globally optimal speed or completed-course acceptance is claimed.

## Measured constraint

In the authorized native browser, a completed video accepted its normal 2x control. An unfinished video had an empty speed menu; setting the media element to 2x was reset to 1x and paused at 67.270077/725.738 seconds. The course task cards specify doublespeed=0. No repeated override or enforcement removal was used. The user's speed authorization is retained; this observation does not establish accepted 2x completion for unfinished tasks.

## Public implementation comparison

- [Samueli924 Python playback](https://github.com/Samueli924/chaoxing/blob/main/api/base.py) initially reports the end and subsequently loops until isPassed. Its scheduler also retries a failed video as audio. These can create misleading progress or repeated full-duration work; the local implementation uses observed player events and terminal bounded failures.
- [dsxksss Flutter playback, v0.1](https://github.com/dsxksss/chaoxing_ft/blob/v0.1/lib/services/video/video_learning_service.dart) preserves bookmarks and limits reporting frequency, but emits isdrag=3 for playing and has no finite unconfirmed-end limit. Those details conflict with this course's observed playing=0 semantics. No code was copied.
- [HaiMFeng browser playback](https://github.com/HaiMFeng/ChaoXing_AutoStudy/blob/main/content.js) sets playbackRate=2 and moves on a fixed timer. That source does not independently prove completion of this course and does not resolve its observed speed reset.

## Implemented approach

Preserve fresh server bookmarks, use play=3 / playing=0 / ended=4, keep shared report throttling, bound transient attempts and end confirmation, and avoid automatic alternate-media or whole-chapter replay. Read the exact completed media card again before marking the chapter successful. Final course verification independently reads every card and requires stable full aggregate progress. String false is not treated as a positive completion response.

142 offline regressions passed, including resumed positions, retry bounds, restrictions, fresh-card mismatches and full-course verification. Live throughput after a serial switch to the new implementation remains to be measured. Compare server-confirmed completions and elapsed time, separately recording resumed work, errors and response latency; do not infer efficacy from configured concurrency alone.

## Native cadence experiment

The course-loaded [player implementation](https://mooc1.chaoxing.com/ananas/videojs-ext/videojs-ext.min.js?v=2026-0902-1207) uses reportTimeInterval with a 60-second default and caps playbackRate when the task disallows speed changes. The task-card decoder already retained reportTimeInterval, but the runner ignored it and used a hardcoded 30 media-second interval. The runner now uses the platform's wall-clock interval, including when speed is greater than 1.

One distinct, previously unstarted 382-second video was tested at the course's required 1x and 60-second interval. Seven reports returned HTTP 200; the seventh returned isPassed=true at 380.13 seconds, and fresh-card confirmation completed at 381.36 seconds. This is actual completion evidence, not just a heartbeat response. The tested probe revision preceded a one-tick position-order correction; that correction and false-string task decoding are covered by the final 146 passing offline tests.

The 8-worker / 30-second batch independently confirmed 8 videos with 244 successful reports in 930 seconds and no failed tasks at the measured checkpoint. The next bounded comparison uses 16 workers with the platform's 60-second interval: expected aggregate report demand is approximately unchanged, while more media tasks can advance concurrently. Retain the shared rate limiter. Final 16-worker acceptance and full-course reconciliation remain pending; this is a measured candidate, not a claim of universal optimality.

## High-concurrency failure and corrected cadence

The 16-worker run ended at 650 seconds after six new videos passed both checks. All 170 report responses were HTTP 200, but one attempt reached its finite unconfirmed-end limit. Fresh server readback remained 92/118; the affected 577-second video's bookmark was only 60 seconds. This rejects the 16-worker run as a stable accepted profile. HTTP success is insufficient.

The next source revision anchors heartbeat cadence to request initiation instead of response completion, so rate-limit queueing and network latency are not repeatedly added to the platform interval. This addresses a concrete scheduling defect; it is not yet proof of the sole cause of the failed video. Known bounded media failures remain failures even if a simultaneous stop occurs. The production scheduler isolates such failures and continues independent chapters; no automatic replay is introduced. A new finite 12-worker run uses fresh server checkpoints and records per-video report timing and completion evidence. Challenges and contradictory completion readback still stop the acceptance run. 148 offline regressions passed; the new live profile remains pending.
