# Test Log - _26_multi_step_tools

Tested 2026-07-20 against `gpt-5.5` through `OpenAIResponses`, Agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Name-only matching across a two-step dispatch lookup.

**Result:** Live run completed 18/18 scored attempts in 63 seconds.
`direct-two-step` passed 6/6 (1.00), `checksum-eight` 4/6 (0.67), and
`checksum-nine` 6/6 (1.00). The middle checksum row exposed skipped second
lookups while the direct workflow stayed saturated.

---

### exact_arguments.py

**Status:** PASS

**Description:** Exact argument matching across both dispatch lookup steps.

**Result:** Live run completed 12/12 scored attempts in 52 seconds.
`route-by-eight` matched both exact records 5/6 times (0.83), and
`route-by-nine` matched them 3/6 times (0.50). Both rows were true partial
binary pass-rate rows.

---

### call_sequence.py

**Status:** PASS

**Description:** Binary code scoring over a dependency-valid three-step execution
sequence and its exact records.

**Result:** The final live run completed 18/18 scored attempts in 66 seconds.
`strict-chain` passed 6/6 (1.00), `route-by-eight` 3/6 (0.50), and
`route-by-nine` 2/6 (0.33). Both checksum rows were true partial binary
pass-rate rows while every passing attempt preserved plan, window, then weather.

The earlier checksum-selected weather-first calibration was discarded because
it rewarded a lookup before its governing weather-station value was returned.
The corrected version keeps the dependency order fixed and moves difficulty to
checksum-selected exact records.

---
