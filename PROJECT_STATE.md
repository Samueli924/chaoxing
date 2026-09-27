# Project State

Last updated: 2026-09-27 UTC
Current version: 4.0.0 plus local consolidation changes
Current objective: Restore canonical local main and integrate reviewed automation capabilities.
Completed work: Restored all 54 main source files; preserved old source/history; added local bank, web provider chain, bounded run duration, dotenv launcher, isolated account batch runner and optional player controls.
Verification: 97 offline tests passed; local bank browser persistence passed; authenticated Brave course/card/player responses verified. See docs/INTEGRATION.md and docs/BROWSER_VERIFICATION_20260927.json.
Pending work: Python authenticated network path, true task-completion readback, paid model/OCR/notifications and cross-platform packaging are unverified. Legacy high-speed/stealth claims are not accepted capabilities.
Known problems: Outbound Python requests in current agent environment raise Bad file descriptor; curl and Brave work. Browser event capture was bounded and not a full HAR.
Deployment status: Local source integration; no production deployment, no account task execution, no exam/assignment submission.
Rollback anchor: origin/main 2089f7e5a51faab180c3ac5bb7220cd69037b737; original local source in .git/chaoxing-recovery-20260927 and old master 52f9fbe (legacy-closty remote).
Next recommended task: Diagnose the Python outbound socket failure in the normal local launch environment, then validate one explicitly selected account/course operation and server-side readback.
