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
| `condition/cel_basic.py` | `input.contains("urgent")` | Branch based on input content |
| `condition/cel_additional_data.py` | `additional_data.priority > 5` | Branch on additional_data fields |
| `condition/cel_session_state.py` | `session_state.retry_count <= 3` | Branch on session state values |
| `condition/cel_previous_step.py` | `previous_step_content.contains("TECHNICAL")` | Branch on previous step output |
| `condition/cel_previous_step_outputs.py` | `previous_step_outputs.Research.contains(...)` | Access a specific step's output by name |

## Router Examples

| File | CEL Expression | What it demonstrates |
|------|---------------|---------------------|
| `router/cel_ternary.py` | `input.contains("video") ? "Video Handler" : "Image Handler"` | Ternary routing on input |
| `router/cel_additional_data_route.py` | `additional_data.route` | Route from caller-specified field |
| `router/cel_session_state_route.py` | `session_state.preferred_handler` | Route from persistent preference |
| `router/cel_previous_step_route.py` | `previous_step_outputs.Classify.contains(...)` | Route based on named step output |
| `router/cel_using_step_choices.py` | `step_choices[0]` | Access available step choices |

## Loop Examples

| File | CEL Expression | What it demonstrates |
|------|---------------|---------------------|
| `loop/cel_iteration_limit.py` | `current_iteration >= 2` | Stop after N iterations |
| `loop/cel_content_keyword.py` | `last_step_content.contains("DONE")` | Stop when agent signals completion |
| `loop/cel_step_outputs_check.py` | `step_outputs.Review.contains("APPROVED")` | Stop when a named step approves |
| `loop/cel_compound_exit.py` | `all_success && current_iteration >= 2` | Compound: success + iteration count |

## Available CEL Variables

### Condition & Router

| Variable | Type | Description |
|----------|------|-------------|
| `input` | string | The workflow input |
| `previous_step_content` | string | Content from the immediately preceding step |
| `previous_step_outputs` | map(string, string) | Map of step name to content string from all previous steps |
| `additional_data` | map | Additional data passed to the workflow |
| `session_state` | map | Session state values |
| `step_choices` | list(string) | *(Router only)* Names of available step choices |

Note: Condition expressions must return a **boolean**. Router expressions must return a **string** (the name of a step from choices).

### Loop

| Variable | Type | Description |
|----------|------|-------------|
| `current_iteration` | int | Current iteration number (1-indexed, after completion) |
| `max_iterations` | int | Maximum iterations configured for the loop |
| `all_success` | bool | True if all steps in this iteration succeeded |
| `last_step_content` | string | Content from the last step in this iteration |
| `step_outputs` | map(string, string) | Map of step name to content string from the current iteration |
