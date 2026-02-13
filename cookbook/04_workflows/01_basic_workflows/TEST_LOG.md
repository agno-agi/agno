# Test Log — 01_basic_workflows

Tested: 2026-02-12 | Branch: cookbook/v25-merge-fixes

## 01_sequence_of_steps

| File | Status | Notes |
|------|--------|-------|
| sequence_of_steps.py | FAIL | httpx.ReadTimeout during model API call |
| sequence_with_functions.py | PASS | Completed in ~45s, blog post workflow with 4 steps |
| workflow_using_steps_nested.py | PASS | Completed in ~87s, article creation with 4 steps |
| workflow_using_steps.py | PASS | Completed in ~42s, renewable energy article |
| workflow_with_file_input.py | PASS | Completed in ~43s, Thai cookbook PDF summarization |
| workflow_with_session_metrics.py | PASS | Completed in ~91s, session metrics displayed correctly |

## 02_step_with_function

| File | Status | Notes |
|------|--------|-------|
| step_with_additional_data.py | PASS | Completed with AI trends analysis output |
| step_with_class.py | PASS | Completed with AI agent frameworks output |
| step_with_function.py | FAIL | httpx.ReadTimeout during model API call |

## 03_function_workflows

| File | Status | Notes |
|------|--------|-------|
| function_workflow.py | FAIL | httpx.ReadTimeout during model API call |

## Summary

- **PASS:** 7
- **FAIL:** 3 (all httpx.ReadTimeout — network/API timeouts, not code errors)
- **SKIP:** 0
