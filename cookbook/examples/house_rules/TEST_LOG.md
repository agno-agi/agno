# Test Log - house_rules

Tested 2026-07-25 against `gpt-5.5` (OpenAIResponses), agno 2.8.2 (source tree at 164f9a6c1).
Entries quote tool calls and printed state. Model prose varies run to run and is paraphrased.

This example is a measurement, not a service: it has nothing to serve, so it stays one
script and has no `test.py`.

### house_rules.py

**Status:** PASS

**Description:** Before/after measurement of three routing rules: 4 tasks x k=4 attempts against an empty knowledge base, insert the rules, 4 x 4 again, then a fingerprint-checked diff. 32 live attempts per run. Run four times end to end to observe the variance.

**Result:** All four runs printed the same numbers, quoted:

```
pass rate without the rules: 0.25
pass rate with the rules:    1.0

ticket-routing       baseline -> current      (env identical, policy identical)
  big-refund        0/4 -> 4/4    +1.00   improved
  chargeback        0/4 -> 4/4    +1.00   improved
  new-account       0/4 -> 4/4    +1.00   improved
  loud-overcharge   4/4 -> 4/4    +0.00
```

Observed range across runs: the before rate is 0.25 in all four of today's runs; during spec verification one run measured 0.3125 because `chargeback` occasionally guesses `fraud` unaided. The after rate has been 1.0 on every observed run. The `(env identical, policy identical)` header is printed by `diff()` only after the two runs' environment fingerprints matched, and the control task `loud-overcharge` stayed 4/4, so the rules fixed three tasks without breaking the one that already passed. Exit 0 on all runs.

---
