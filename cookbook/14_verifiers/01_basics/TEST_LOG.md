# Test Log

## 2026-08-26 — gpt-5.5, demo venv

### verify_done.py

**Status:** PASS

**Description:** Callable verifier (report.md must exist) with FileTools. The model wrote the file on its first attempt; verifier passed; status COMPLETED, record verified/passed with 1 attempt.

**Result:** Success. With a lazier model the second attempt is exercised; the re-entry path is pinned by the unit suite.

---

### unverified.py

**Status:** PASS

**Description:** Impossible verifier with max_attempts=2 on a SqliteDb agent. Run ended UNVERIFIED / exhausted after exactly 2 attempts; the persisted row read back with status UNVERIFIED and the full record (unverified / exhausted).

**Result:** Success.

---

### streamed.py

**Status:** PASS

**Description:** Streaming run with stream_events: VerificationStarted / VerificationCompleted events rendered live per attempt, verdict summaries included.

**Result:** Success.

---

### check_policy.py

**Status:** PASS (2026-08-27, gpt-5.5, demo venv)

**Description:** Per-check policy: a required file check, an advisory length check (required=False), and a JudgeScorer gated by run_when on the required checks passing. Attempt 0: both cheap checks passed, so the judge ran and failed the draft; the model rewrote; attempt 1 passed all three. The judge never runs while required checks fail, so failed attempts never pay for a judge call.

**Result:** Success.

---
