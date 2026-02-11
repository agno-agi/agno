# Test Log: 06_quick_tests

**Date:** 2026-02-10
**Environment:** `.venvs/demo/bin/python`
**Model:** gpt-4o (01-03), claude-sonnet-4-20250514 (04)
**Services:** pgvector (01, 02, 04), none (03)

## Structure Check

**Result:** Checked 4 file(s). Violations: 0
**Details:** Clean

---

## Runtime Results

### 01_async_user_profile.py

**Status:** PASS
**Time:** ~35s
**Description:** Async variant of user profile learning. Uses asyncio.run with Diana Prince / Di. Cross-session recall confirmed.
**Output:** Async profile extraction and recall worked identically to sync variant.
**Triage:** n/a

---

### 02_learning_true_shorthand.py

**Status:** PASS
**Time:** ~30s
**Description:** Shorthand `learning=True` syntax for enabling learning. Profile and memory extraction for Charlie Brown / Chuck.
**Output:** Shorthand enabled all learning features, profile and memories extracted.
**Triage:** n/a

---

### 03_no_db_graceful.py

**Status:** PASS
**Time:** ~5s
**Description:** Graceful degradation when no database is configured. Agent works without DB, profile not persisted. Warning logged.
**Output:** Agent responded normally, warning about missing DB logged, no crash.
**Triage:** n/a

---

### 04_claude_model.py

**Status:** PASS
**Time:** ~25s
**Description:** Learning with Claude model (Anthropic). User profile for Bruce Wayne / Batman. Cross-session recall confirmed.
**Output:** Claude model extracted profile and recalled it in second session.
**Triage:** n/a

---

## Summary

| File | Status | Triage | Notes |
|------|--------|--------|-------|
| 01_async_user_profile.py | PASS | n/a | Async variant works |
| 02_learning_true_shorthand.py | PASS | n/a | Shorthand syntax works |
| 03_no_db_graceful.py | PASS | n/a | Graceful degradation, no crash |
| 04_claude_model.py | PASS | n/a | Claude model compatible |

**Totals:** 4 PASS, 0 FAIL, 0 SKIP, 0 ERROR
