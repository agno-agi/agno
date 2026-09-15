# Test Log: 02_shell

> Tested 2026-09-15 against `gpt-5.6-luna` (OpenAIResponses), demo venv, agno source tree.

### tests_must_pass.py

**Status:** PASS

**Description:** ShellVerifier runs `pytest -q` from a checks/ directory the agent cannot write, against a src/calc.py with a broken add; the suite also tests a subtract function the prompt never mentions.

**Result:** Exit 0. `Attempt 0: FAIL | exit 1 | 1 failed, 1 passed` (add fixed, subtract missing), `Attempt 1: PASS | exit 0` after the model added subtract; `Verification: verified / passed`. Setup rewrites both fixture files every run; four consecutive runs all went FAIL then PASS (one showed `2 failed` on attempt 0 from the model's first edit, then passed).

---
