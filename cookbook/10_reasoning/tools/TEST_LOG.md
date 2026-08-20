# TEST_LOG



## Verification - 2026-08-20 round 4, focus areas (feat/v3.0, base ca5697ecd9)

**Environment:** `.venvs/demo/bin/python`, batch runner (240s timeout) + manual retries

| File | Status | Note |
|---|---|---|
| openai_reasoning_tools.py | PASS |  |
| claude_reasoning_tools.py | FAIL-STALE-MODEL | claude-sonnet-4-20250514 now 404s at the API |

---

## Verification - 2026-08-18 round 3 (feat/v3.0, base b10e70d5d4)

**Environment:** `.venvs/demo/bin/python`, batch runner with 240s timeout

| File | Status | Note |
|---|---|---|
| reasoning_tools.py | PASS |  |

---

### Structure Validation

**Status:** PASS

**Description:** Validated cookbook structure compliance and Python compilation for this directory's examples.

**Result:** Files in this directory pass structure checks and compile successfully.

---
