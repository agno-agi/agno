# Test Log: 04_fingerprints

> Tested 2026-09-15 against `gpt-5.6-luna` (OpenAIResponses), demo venv, agno source tree.

### unchanged_state_guard.py

**Status:** PASS

**Description:** GitWorktreeFingerprint with stop_on_unchanged_state=True over a scratch git repo under tmp/verifiers/ (re-running `git init` on it is a no-op); the check requires CHANGELOG.md and the agent's FileTools can only list and search.

**Result:** Exit 0 on two runs in a row, identical output. `Attempt 0: passed False | state_unchanged True`; `Verification: unverified / unchanged_state`, `Attempts: 1 of 5`.

---

### callable_fingerprint.py

**Status:** PASS

**Description:** CallableFingerprint over a sha256 of an in-memory ledger; the check requires an entry tagged [approved] the prompt never mentions.

**Result:** Exit 0. `Attempt 0: passed False | state_unchanged False` (the ledger gained an untagged entry), `Attempt 1: passed True | state_unchanged False`; `Verification: verified / passed`. Ledger: `['Decision: Adopt code review.', '[approved] Decision: Adopt code review.']`.

---
