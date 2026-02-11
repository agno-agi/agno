# Test Results Summary: 08_learning

**Date:** 2026-02-10
**Session:** 10 of 20
**Total Files:** 31

## Results

| Subdirectory | Total | PASS | FAIL | SKIP | ERROR |
|-------------|------:|-----:|-----:|-----:|------:|
| 00_quickstart/ | 3 | 3 | 0 | 0 | 0 |
| 01_basics/ | 9 | 9 | 0 | 0 | 0 |
| 02_user_profile/ | 3 | 3 | 0 | 0 | 0 |
| 03_session_context/ | 2 | 2 | 0 | 0 | 0 |
| 04_entity_memory/ | 2 | 2 | 0 | 0 | 0 |
| 05_learned_knowledge/ | 2 | 2 | 0 | 0 | 0 |
| 06_quick_tests/ | 4 | 4 | 0 | 0 | 0 |
| 07_patterns/ | 2 | 2 | 0 | 0 | 0 |
| 08_custom_stores/ | 2 | 2 | 0 | 0 | 0 |
| 09_decision_logs/ | 2 | 2 | 0 | 0 | 0 |
| **Total** | **31** | **31** | **0** | **0** | **0** |

## Failures & Errors

None after fixes applied.

### Regressions Found and Fixed

| File | Original Error | Fix | Triage |
|------|---------------|-----|--------|
| `09_decision_logs/01_basic_decision_log.py` | `AttributeError: 'Agent' object has no attribute 'get_learning_machine'` | Changed `agent.get_learning_machine()` to `agent.learning_machine` (property) | regression (fixed) |
| `09_decision_logs/02_decision_log_always.py` | Same as above | Same fix | regression (fixed) |

## Structure Violations

None. Checked 31 files, 0 violations. Golden reference section is clean.

## Notes

- This is the **golden reference** section for the cookbook restructure. 100% PASS rate confirms quality.
- All files use pgvector except `06_quick_tests/03_no_db_graceful.py` (intentionally no DB) and `08_custom_stores/01_minimal_custom_store.py` (in-memory store).
- `06_quick_tests/04_claude_model.py` uses Anthropic Claude instead of OpenAI — both API keys were available.
- The `get_learning_machine()` → `learning_machine` property regression in `09_decision_logs/` was the only issue found. It was a stale method call from before the restructure renamed the getter to a property. Fix applied and verified.
- No other `get_learning_machine()` references remain in the cookbook.
