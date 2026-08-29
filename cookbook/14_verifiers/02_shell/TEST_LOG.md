# Test Log

## 2026-08-26 — gpt-5.5, demo venv

### tests_must_pass.py

**Status:** PASS

**Description:** ShellVerifier(sys.executable -m pytest -q) over a scratch project with a deliberately broken function. The agent read the code, fixed calc.py, and the suite passed; verified/passed.

**Result:** Success. An earlier draft used a bare "python" command, which is absent on macOS PATH — the harness-error path surfaced it as "harness error: exit 127" and the run correctly ended UNVERIFIED, which is itself the designed fail-closed behavior.

---
