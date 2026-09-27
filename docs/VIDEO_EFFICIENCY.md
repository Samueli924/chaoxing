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
