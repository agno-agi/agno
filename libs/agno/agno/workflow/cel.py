"""CEL (Common Expression Language) support for workflow steps.

Provides safe, sandboxed expression evaluation for Condition evaluators and
Loop end conditions. Enables UI-driven workflow configuration by allowing
conditions to be defined as strings rather than Python callables.

CEL spec: https://github.com/google/cel-spec
"""

import json
import re
from typing import Any, Dict, List, Optional

from agno.utils.log import logger

try:
    import celpy
    from celpy import celtypes

    CEL_AVAILABLE = True
except ImportError:
    CEL_AVAILABLE = False
    celpy = None  # type: ignore
    celtypes = None  # type: ignore

# Regex for simple Python identifiers (function names)
_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Characters/tokens that indicate a CEL expression rather than a function name
_CEL_INDICATORS = [
    ".", "(", ")", "[", "]",
    "==", "!=", "<=", ">=", "<", ">",
    "&&", "||", "!",
    "+", "-", "*", "/", "%",
    "?", ":", '"', "'",
    "true", "false", " in ",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_cel_expression(expression: str) -> bool:
    """Validate a CEL expression without evaluating it.

    Useful for UI validation before saving a workflow configuration.
    """
    if not CEL_AVAILABLE:
        logger.warning("cel-python is not installed. Install with: pip install cel-python")
        return False

    try:
        env = celpy.Environment()
        env.compile(expression)
        return True
    except Exception as e:
        logger.debug(f"CEL expression validation failed: {e}")
        return False


def is_cel_expression(value: str) -> bool:
    """Determine if a string is a CEL expression vs a function name.

    Simple identifiers like ``my_evaluator`` return False.
    Anything containing operators, dots, parens, etc. returns True.
    """
    if _IDENTIFIER_RE.match(value):
        return False

    return any(indicator in value for indicator in _CEL_INDICATORS)


def evaluate_cel_condition(
    expression: str,
    step_input: "StepInput",  # type: ignore  # noqa: F821
    session_state: Optional[Dict[str, Any]] = None,
) -> bool:
    """Evaluate a CEL expression for a Condition evaluator.

    Context variables:
        - input: The workflow input as a string
        - previous_step_content: Content from the previous step
        - has_previous_step_content: Whether previous content exists
        - previous_step_names: List of previous step names
        - additional_data: Map of additional data passed to the workflow
        - session_state: Map of session state values
    """
    return _evaluate_cel(expression, _build_condition_context(step_input, session_state))


def evaluate_cel_loop_end_condition(
    expression: str,
    iteration_results: "List[StepOutput]",  # type: ignore  # noqa: F821
    iteration: int = 0,
) -> bool:
    """Evaluate a CEL expression as a Loop end condition.

    Context variables:
        - iteration: Current iteration number (0-indexed)
        - num_steps: Number of step outputs in the current iteration
        - all_success: True if all steps succeeded
        - any_failure: True if any step failed
        - last_content: Content string from the last step
        - total_content_length: Sum of all step content lengths
        - max_content_length: Length of the longest step content
    """
    return _evaluate_cel(expression, _build_loop_context(iteration_results, iteration))


def evaluate_cel_router(
    expression: str,
    step_input: "StepInput",  # type: ignore  # noqa: F821
    session_state: Optional[Dict[str, Any]] = None,
) -> str:
    """Evaluate a CEL expression for a Router selector.

    Returns the name of the step to execute as a string.

    Context variables (same as Condition):
        - input: The workflow input as a string
        - previous_step_content: Content from the previous step
        - has_previous_step_content: Whether previous content exists
        - previous_step_names: List of previous step names
        - additional_data: Map of additional data passed to the workflow
        - session_state: Map of session state values

    Example CEL expressions:
        - 'input.contains("video") ? "video_step" : "image_step"'
        - 'additional_data.route'
        - 'session_state.preferred_handler'
    """
    return _evaluate_cel_string(expression, _build_condition_context(step_input, session_state))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _evaluate_cel(expression: str, context: Dict[str, Any]) -> bool:
    """Core CEL evaluation: compile, run, and coerce to bool."""
    if not CEL_AVAILABLE:
        raise RuntimeError("cel-python is not installed. Install with: pip install cel-python")

    try:
        env = celpy.Environment()
        prog = env.program(env.compile(expression))
        result = prog.evaluate({k: _to_cel(v) for k, v in context.items()})

        if isinstance(result, celtypes.BoolType):
            return bool(result)
        if isinstance(result, bool):
            return result

        logger.warning(f"CEL expression '{expression}' returned {type(result).__name__}, converting to bool")
        return bool(result)

    except Exception as e:
        logger.error(f"CEL evaluation failed for '{expression}': {e}")
        raise ValueError(f"Failed to evaluate CEL expression '{expression}': {e}") from e


def _evaluate_cel_string(expression: str, context: Dict[str, Any]) -> str:
    """CEL evaluation that returns a string result (for Router selector)."""
    if not CEL_AVAILABLE:
        raise RuntimeError("cel-python is not installed. Install with: pip install cel-python")

    try:
        env = celpy.Environment()
        prog = env.program(env.compile(expression))
        result = prog.evaluate({k: _to_cel(v) for k, v in context.items()})

        if isinstance(result, celtypes.StringType):
            return str(result)
        if isinstance(result, str):
            return result

        # Convert other types to string
        logger.warning(f"CEL expression '{expression}' returned {type(result).__name__}, converting to string")
        return str(result)

    except Exception as e:
        logger.error(f"CEL evaluation failed for '{expression}': {e}")
        raise ValueError(f"Failed to evaluate CEL expression '{expression}': {e}") from e


def _to_cel(value: Any) -> Any:
    """Convert a Python value to a CEL-compatible type."""
    if not CEL_AVAILABLE or value is None:
        return value

    if isinstance(value, bool):
        return celtypes.BoolType(value)
    if isinstance(value, int):
        return celtypes.IntType(value)
    if isinstance(value, float):
        return celtypes.DoubleType(value)
    if isinstance(value, str):
        return celtypes.StringType(value)
    if isinstance(value, list):
        return celtypes.ListType([_to_cel(item) for item in value])
    if isinstance(value, dict):
        return celtypes.MapType({celtypes.StringType(k): _to_cel(v) for k, v in value.items()})

    return celtypes.StringType(str(value))


def _build_condition_context(
    step_input: "StepInput",  # type: ignore  # noqa: F821
    session_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build context for Condition CEL evaluation from StepInput."""
    input_str = ""
    if step_input.input is not None:
        input_str = step_input.get_input_as_string() or ""

    previous_content = ""
    if step_input.previous_step_content is not None:
        if hasattr(step_input.previous_step_content, "model_dump_json"):
            previous_content = step_input.previous_step_content.model_dump_json()
        elif isinstance(step_input.previous_step_content, dict):
            previous_content = json.dumps(step_input.previous_step_content, default=str)
        else:
            previous_content = str(step_input.previous_step_content)

    previous_step_names: List[str] = []
    if step_input.previous_step_outputs:
        previous_step_names = list(step_input.previous_step_outputs.keys())

    return {
        "input": input_str,
        "previous_step_content": previous_content,
        "has_previous_step_content": bool(step_input.previous_step_content),
        "previous_step_names": previous_step_names,
        "additional_data": step_input.additional_data or {},
        "session_state": session_state or {},
    }


def _build_loop_context(
    iteration_results: "List[StepOutput]",  # type: ignore  # noqa: F821
    iteration: int = 0,
) -> Dict[str, Any]:
    """Build context for Loop end condition CEL evaluation from iteration results."""
    all_success = True
    any_failure = False
    total_content_length = 0
    max_content_length = 0
    last_content = ""

    for result in iteration_results:
        content = str(result.content) if result.content else ""
        content_len = len(content)
        total_content_length += content_len
        if content_len > max_content_length:
            max_content_length = content_len
        last_content = content
        if not result.success:
            all_success = False
            any_failure = True

    return {
        "iteration": iteration,
        "num_steps": len(iteration_results),
        "all_success": all_success,
        "any_failure": any_failure,
        "last_content": last_content,
        "total_content_length": total_content_length,
        "max_content_length": max_content_length,
    }
