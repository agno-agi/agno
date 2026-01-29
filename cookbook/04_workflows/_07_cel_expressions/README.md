# CEL Expressions in Workflows

Examples demonstrating [CEL (Common Expression Language)](https://github.com/google/cel-spec) expressions as evaluators in workflow steps.

CEL expressions let you define conditions as strings instead of Python callables, enabling UI-driven workflow configuration and database storage.

## Setup

```bash
pip install cel-python
```

## Condition Examples (10)

| File | CEL Expression | What it demonstrates |
|------|---------------|---------------------|
| `condition/cel_basic.py` | `input.contains("urgent")` | Route based on input content |
| `condition/cel_session_state.py` | `session_state.retry_count <= 3` | Branch on session state values |
| `condition/cel_additional_data.py` | `additional_data.priority > 5` | Branch on additional_data fields |
| `condition/cel_previous_step.py` | `previous_step_content.contains("TECHNICAL")` | Branch on previous step output |
| `condition/cel_has_previous_step.py` | `has_previous_step_content` | Check if previous step produced output |
| `condition/cel_previous_step_contents.py` | `previous_step_contents.size() >= 2` | Check number of previous step outputs |
| `condition/cel_compound_and.py` | `input.contains("urgent") && additional_data.priority > 7` | Compound AND condition |
| `condition/cel_compound_or.py` | `input.contains("error") \|\| input.contains("critical")` | Compound OR condition |
| `condition/cel_nested_additional_data.py` | `additional_data.user.role == "admin"` | Nested additional_data access |
| `condition/cel_validate.py` | N/A | Validate expressions before use |

## Router Examples (10)

| File | CEL Expression | What it demonstrates |
|------|---------------|---------------------|
| `router/cel_ternary.py` | `input.contains("video") ? "Video Handler" : "Image Handler"` | Ternary routing on input |
| `router/cel_additional_data_route.py` | `additional_data.route` | Route from caller-specified field |
| `router/cel_session_state_route.py` | `session_state.preferred_handler` | Route from persistent preference |
| `router/cel_previous_step_route.py` | `previous_step_content.contains("BILLING") ? ...` | Chained ternary on classifier output |
| `router/cel_nested_ternary.py` | `input.contains("python") ? ... : input.contains("js") ? ...` | Multi-way routing with chained ternary |
| `router/cel_compound_selector.py` | `(additional_data.tier == "premium" \|\| ...) ? ...` | Compound && and \|\| in selector |
| `router/cel_input_length.py` | `input.size() > 100 ? ...` | Route based on input length |
| `router/cel_has_previous_content_route.py` | `has_previous_step_content ? ...` | Route on previous content existence |
| `router/cel_nested_additional_data_route.py` | `additional_data.config.output_format == "json" ? ...` | Nested field access for routing |
| `router/cel_previous_step_contents_route.py` | `previous_step_contents.size() > 1 ? ...` | Route based on number of prior outputs |

## Loop Examples (10)

| File | CEL Expression | What it demonstrates |
|------|---------------|---------------------|
| `loop/cel_content_length.py` | `max_content_length > 200` | Stop when any step output is substantial |
| `loop/cel_total_content_length.py` | `total_content_length > 500` | Stop when combined output is large |
| `loop/cel_iteration_limit.py` | `iteration >= 2` | Stop after N iterations |
| `loop/cel_max_iterations_ratio.py` | `iteration >= max_iterations / 2` | Stop at fraction of max |
| `loop/cel_success_check.py` | `all_success` | Stop on first successful iteration |
| `loop/cel_any_failure.py` | `any_failure` | Stop on first failure |
| `loop/cel_content_keyword.py` | `last_step_content.contains("DONE")` | Stop when agent signals completion |
| `loop/cel_num_steps.py` | `num_steps >= 3 && all_success` | Compound: step count + success |
| `loop/cel_step_contents_check.py` | `step_contents.size() >= 2 && all_success` | Check step_contents list |
| `loop/cel_compound_exit.py` | `max_content_length > 300 \|\| (iteration >= 2 && all_success)` | Compound exit with OR |

## Available CEL Variables

### Condition & Router

- `input` - The workflow input as a string
- `previous_step_content` - Content from the previous step
- `has_previous_step_content` - Whether previous content exists
- `previous_step_contents` - List of content strings from all previous steps
- `additional_data` - Map of additional data passed to the workflow
- `session_state` - Map of session state values

Note: Condition expressions must return a **boolean**. Router expressions must return a **string** (the name of a step from choices).

### Loop

- `iteration` - Current iteration number (0-indexed)
- `max_iterations` - Maximum iterations configured for the loop
- `num_steps` - Number of step outputs in the current iteration
- `all_success` - True if all steps succeeded
- `any_failure` - True if any step failed
- `step_contents` - List of content strings from all steps in order
- `last_step_content` - Content string from the last step
- `total_content_length` - Sum of all step content lengths
- `max_content_length` - Length of the longest step content
