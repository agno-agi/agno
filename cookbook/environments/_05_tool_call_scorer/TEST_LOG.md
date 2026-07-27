# Test Log - _05_tool_call_scorer

## Re-test 2026-07-20 — fix/cookbooks-claude (Agno 2.8.0 source)

### basic.py — FIXED

**Fix:** the presence-only check saturated (gpt-5.5 always makes a required tool
call), and the old parity routing let an unnecessary call count as success. Added a
decoy `lookup_backup_carrier`, a routing rule that tempts it, and
`allow_additional=False` — matching the file's own prose ("without making an
unnecessary lookup count as success"). The zone is now the inconsistently-slipped
backup call.

**Grid (k=6):** `direct-lookup` 6/6; `checksum-route-a` 0/6; `checksum-route-b` 5/6
(0.83, zone).

`strict_tools.py` (checksum-route-a 0.50, checksum-route-b 0.67) and
`with_arguments.py` (checksum-date 0.50) re-ran clean and unchanged.

---

Tested 2026-07-20 against `gpt-5.5` through `OpenAIResponses`, Agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Name-only execution matching for three tasks whose correct routing
requires a current shipping-policy lookup.

**Result:** Final live run after correcting the task/scorer contract:
`direct-lookup` executed the required lookup 6/6 times (1.00),
`checksum-route-a` 4/6 (0.67), and `checksum-route-b` 5/6 (0.83). Both routed
rows are true partial binary pass-rate rows. The earlier ambiguous version was
discarded because it rewarded a lookup even when the prompt permitted skipping it.

---

### with_arguments.py

**Status:** PASS

**Description:** Tool execution matching with an exact region, service, and date argument subset.

**Result:** Final live rerun after the constant-string cleanup matched the exact
argument subset at 5/6 for `checksum-date` (0.83), 4/6 for `checksum-service`
(0.67), and 6/6 for `checksum-region` (1.00).

Two earlier calibrations saturated. The original dated rows both scored 6/6;
the first ambiguity revision also scored 6/6 on all three rows. Replacing vague
wording with deterministic but difficult checksum routing exposed the middle
band without changing what the scorer verifies.

---

### strict_tools.py

**Status:** PASS

**Description:** Strict execution matching that rejects the unexpected
`minutes_between` tool name while requiring the lookup name.

**Result:** Final live rerun after clarifying strict name-set semantics:
`lean-anchor` passed 6/6 (1.00), `checksum-route-a` 3/6 (0.50), and
`checksum-route-b` 4/6 (0.67). Failures on the routed rows were successful
extra `minutes_between` executions, exactly what strict mode is meant to catch.
This is name-set strictness, not a check on duplicate calls to an expected tool.

The initial two-row calibration was a failed all-full grid: both
`borderline-subtraction` and `tempting-calculator` scored 6/6. Checksum-based
conditional tool routing replaced it.

---
