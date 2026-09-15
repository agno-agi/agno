# Test Log - _22_sql_generation

Tested 2026-07-20 live against `gpt-5.5`, agno 2.7.4, using
`.venvs/demo/bin/python` with `OPENAI_API_KEY` loaded from `.envrc`.

### basic.py

**Status:** PASS

**Description:** Recursive inventory-state replay with accepted, rejected, duplicate,
and unknown reservation references.

**Result:** 8 attempts in 48s. `inventory-state` landed at 7/8 (0.875), all
scored. The failed query reached the right recursive shape but used non-text
`json_object()` labels and SQLite rejected it. Two earlier versions were discarded
after saturating 8/8: a temporal ledger, then marginal tiers plus promotion precedence;
a recursive subscription state machine also saturated 8/8. Reserve acceptance plus
single-use release state was the change that escaped the wall of full bars.

---

### joins.py

**Status:** PASS

**Description:** Multi-table first-human-response query measured in business minutes
across a holiday and overnight boundaries.

**Result:** 8 attempts in 18s, all scored. `business-minute-sla` was 7/8
(0.875). The failing query returned both organizations at 100%, exposing a business
minute boundary error. The first version used a fixed four-hour wall-clock SLA and
saturated 8/8; adding per-organization thresholds, a holiday, overnight spans, bot
and pre-open distractors, and exact minute semantics created the useful middle band.

---

### window_functions.py

**Status:** PASS

**Description:** Recursive inventory state retained per event, followed by windowed
upward threshold crossings.

**Result:** 16 attempts in 85s, all scored. `stateful-threshold-crossing` was
7/8 (0.875); `final-state-audit` saturated at 8/8. The failing crossing query used
non-text JSON labels and SQLite rejected it. Three earlier grids saturated 8/8: an
effective-dated price crossing, the same stream plus returns, and marginal tiers plus
promotion precedence. Replacing arithmetic windows with reserve acceptance,
single-use releases, a recursive trajectory, and repeat up-crossings finally exposed
the middle band.

---
