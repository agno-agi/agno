# CEL Expressions in Workflows

Examples demonstrating [CEL (Common Expression Language)](https://github.com/google/cel-spec) expressions as evaluators in workflow steps.

CEL expressions let you define conditions as strings instead of Python callables, enabling UI-driven workflow configuration and database storage.

## Setup

```bash
pip install cel-python
```

## Condition Examples

| File | CEL Expression | What it demonstrates |
|------|---------------|---------------------|
| `condition/cel_basic.py` | `input.contains("urgent")` | Route based on input content |
| `condition/cel_session_state.py` | `session_state.retry_count <= 3` | Branch on session state values |
| `condition/cel_additional_data.py` | `additional_data.priority > 5` | Branch on additional_data fields |
| `condition/cel_previous_step.py` | `previous_step_content.contains("TECHNICAL")` | Branch on previous step output |
| `condition/cel_validate.py` | N/A | Validate expressions before use |

## Router Examples

| File | CEL Expression | What it demonstrates |
|------|---------------|---------------------|
| `router/cel_ternary.py` | `input.contains("video") ? "Video Handler" : "Image Handler"` | Ternary routing on input |
| `router/cel_additional_data_route.py` | `additional_data.route` | Route from caller-specified field |
| `router/cel_session_state_route.py` | `session_state.preferred_handler` | Route from persistent preference |

## Loop Examples

| File | CEL Expression | What it demonstrates |
|------|---------------|---------------------|
| `loop/cel_content_length.py` | `max_content_length > 200` | Stop when output is substantial |
| `loop/cel_iteration_limit.py` | `iteration >= 2` | Stop after N iterations |
| `loop/cel_success_check.py` | `all_success` | Stop on first successful iteration |
| `loop/cel_content_keyword.py` | `last_content.contains("DONE")` | Stop when agent signals completion |

## Available CEL Variables

### Condition & Router

- `input` - The workflow input as a string
- `previous_step_content` - Content from the previous step
- `has_previous_step_content` - Whether previous content exists
- `previous_step_names` - List of previous step names
- `additional_data` - Map of additional data passed to the workflow
- `session_state` - Map of session state values

Note: Condition expressions must return a **boolean**. Router expressions must return a **string** (the name of a step from choices).

### Loop

- `iteration` - Current iteration number (0-indexed)
- `num_steps` - Number of step outputs in the current iteration
- `all_success` - True if all steps succeeded
- `any_failure` - True if any step failed
- `last_content` - Content string from the last step
- `total_content_length` - Sum of all step content lengths
- `max_content_length` - Length of the longest step content
