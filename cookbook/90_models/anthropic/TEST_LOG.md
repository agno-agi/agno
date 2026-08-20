# TEST_LOG



## Verification - 2026-08-20 round 4, focus areas (feat/v3.0, base ca5697ecd9)

**Environment:** `.venvs/demo/bin/python`, batch runner (240s timeout) + manual retries

| File | Status | Note |
|---|---|---|
| adaptive_thinking.py | PASS |  |
| tool_use.py | FAIL-STALE-MODEL | claude-sonnet-4-20250514 now 404s at the API; script exits 0 so the failure is silent |

---

## Verification - 2026-08-18 round 3 (feat/v3.0, base b10e70d5d4)

**Environment:** `.venvs/demo/bin/python`, batch runner with 240s timeout

| File | Status | Note |
|---|---|---|
| basic.py | PASS |  |

---

No cookbook tests have been recorded for this directory yet.
