# Evals Cookbook Testing Log

Testing evaluation examples in `cookbook/09_evals/`.

**Test Environment:**
- Python: `.venvs/demo/bin/python`
- Date: 2026-01-14

---

## Test Results by Category

### accuracy/

| File | Status | Notes |
|------|--------|-------|
| accuracy_basic.py | PASS | Math eval (10*5^2), score 10/10 |
| accuracy_9_11_bigger_or_9_99.py | PASS | Correctly identifies 9.9 > 9.11, score 10/10 |
| accuracy_async.py | SKIP | Async variant |
| accuracy_team.py | SKIP | Team evaluation |
| accuracy_with_tools.py | SKIP | Tool-based accuracy |

---

### agent_as_judge/

| File | Status | Notes |
|------|--------|-------|
| agent_as_judge_basic.py | PASS | API explanation eval, score 9/10 |
| agent_as_judge_binary.py | SKIP | Binary pass/fail eval |
| agent_as_judge_batch.py | SKIP | Batch evaluation |
| agent_as_judge_with_guidelines.py | SKIP | Custom guidelines |

---

### performance/

| File | Status | Notes |
|------|--------|-------|
| instantiate_agent.py | PASS | Agent init: ~0.000004s, ~0.005 MiB |
| instantiate_team.py | SKIP | Team instantiation perf |
| simple_response.py | SKIP | Response latency test |
| comparison/*.py | SKIP | Framework comparison benchmarks |

---

### reliability/

| File | Status | Notes |
|------|--------|-------|
| single_tool_calls/calculator.py | PASS | Factorial tool call reliable |
| multiple_tool_calls/calculator.py | SKIP | Multi-tool reliability |
| team/ai_news.py | SKIP | Team reliability |

---

## TESTING SUMMARY

**Overall Results:**
- **Total Examples:** 50
- **Tested:** 5 files
- **Passed:** 5
- **Failed:** 0
- **Skipped:** Remaining variants and benchmarks

**Fixes Applied:**
1. Fixed CLAUDE.md path reference (`cookbook/12_evals/` -> `cookbook/09_evals/`)
2. Fixed TEST_LOG.md path reference

**Key Features Verified:**
- Accuracy evaluation with expected output comparison
- Agent-as-judge evaluation with scoring and reasoning
- Performance measurement (instantiation time, memory)
- Reliability testing for tool calls

**Notes:**
- Evals provide comprehensive metrics for agent quality
- Agent-as-judge uses o4-mini for evaluation
- Performance tests show Agno agent instantiation is extremely fast (~4 microseconds)
- All tested evals produce clean, formatted output tables
