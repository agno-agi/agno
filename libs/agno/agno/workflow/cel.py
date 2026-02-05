"""CEL (Common Expression Language) support for workflow steps.

CEL spec: https://github.com/google/cel-spec
"""

import json
import re
from typing import Any, Dict, List, Optional, Union

from agno.utils.log import logger

try:
    import celpy
    from celpy import celtypes

    CEL_AVAILABLE = True
    CelValue = Union[
        celtypes.BoolType,
        celtypes.IntType,
        celtypes.DoubleType,
        celtypes.StringType,
        celtypes.ListType,
        celtypes.MapType,
    ]
except ImportError:
    CEL_AVAILABLE = False
    celpy = None  # type: ignore
    celtypes = None  # type: ignore
    CelValue = Any  # type: ignore

# Type alias for Python values that can be converted to CEL
PythonValue = Union[None, bool, int, float, str, List[Any], Dict[str, Any]]

# Regex for simple Python identifiers (function names)
_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Characters/tokens that indicate a CEL expression rather than a function name
_CEL_INDICATORS = [
    ".",
    "(",
    ")",
    "[",
    "]",
    "==",
    "!=",
    "<=",
    ">=",
    "<",
    ">",
    "&&",
    "||",
    "!",
    "+",
    "-",
    "*",
    "/",
    "%",
    "?",
    ":",
    '"',
    "'",
    "true",
    "false",
    " in ",
]


# ********** Public Functions **********
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


def evaluate_cel_condition_evaluator(
    expression: str,
    step_input: "StepInput",  # type: ignore  # noqa: F821
    session_state: Optional[Dict[str, Any]] = None,
) -> bool:
    """Evaluate a CEL expression for a Condition evaluator.

    Context variables:
        - input: The workflow input as a string
        - previous_step_content: Content from the previous step
        - previous_step_outputs: Map of step name to content string from all previous steps
        - additional_data: Map of additional data passed to the workflow
        - session_state: Map of session state values
    """
    return _evaluate_cel(expression, _build_step_input_context(step_input, session_state))


def evaluate_cel_loop_end_condition(
    expression: str,
    iteration_results: "List[StepOutput]",  # type: ignore  # noqa: F821
    current_iteration: int = 0,
    max_iterations: int = 3,
) -> bool:
    """Evaluate a CEL expression as a Loop end condition.

    Context variables:
        - current_iteration: Current iteration number (1-indexed, after completion)
        - max_iterations: Maximum iterations configured for the loop
        - all_success: True if all steps in this iteration succeeded
        - last_step_content: Content string from the last step in this iteration
        - step_outputs: Map of step name to content string from the current iteration
    """
    return _evaluate_cel(
        expression, _build_loop_step_output_context(iteration_results, current_iteration, max_iterations)
    )


def evaluate_cel_router_selector(
    expression: str,
    step_input: "StepInput",  # type: ignore  # noqa: F821
    session_state: Optional[Dict[str, Any]] = None,
    step_choices: Optional[List[str]] = None,
) -> str:
    """Evaluate a CEL expression for a Router selector.

    Returns the name of the step to execute as a string.

    Context variables (same as Condition, plus step_choices):
        - input: The workflow input as a string
        - previous_step_content: Content from the previous step
        - previous_step_outputs: Map of step name to content string from all previous steps
        - additional_data: Map of additional data passed to the workflow
        - session_state: Map of session state values
        - step_choices: List of step names available to the selector
    """
    context = _build_step_input_context(step_input, session_state)
    context["step_choices"] = step_choices or []
    return _evaluate_cel_string(expression, context)


# ********** Internal Functions **********
def _evaluate_cel_raw(expression: str, context: Dict[str, Any]) -> Any:
    """Core CEL evaluation: compile, run, and return the raw result."""
    if not CEL_AVAILABLE:
        raise RuntimeError("cel-python is not installed. Install with: pip install cel-python")

    try:
        env = celpy.Environment()
        prog = env.program(env.compile(expression))
        return prog.evaluate({k: _to_cel(v) for k, v in context.items()})
    except Exception as e:
        logger.error(f"CEL evaluation failed for '{expression}': {e}")
        raise ValueError(f"Failed to evaluate CEL expression '{expression}': {e}") from e


def _evaluate_cel(expression: str, context: Dict[str, Any]) -> bool:
    """CEL evaluation that coerces the result to bool."""
    result = _evaluate_cel_raw(expression, context)

    if isinstance(result, celtypes.BoolType):
        return bool(result)
    if isinstance(result, bool):
        return result

    logger.warning(f"CEL expression '{expression}' returned {type(result).__name__}, converting to bool")
    return bool(result)


def _evaluate_cel_string(expression: str, context: Dict[str, Any]) -> str:
    """CEL evaluation that coerces the result to string (for Router selector)."""
    result = _evaluate_cel_raw(expression, context)

    if isinstance(result, celtypes.StringType):
        return str(result)
    if isinstance(result, str):
        return result

    logger.warning(f"CEL expression '{expression}' returned {type(result).__name__}, converting to string")
    return str(result)


def _to_cel(value: PythonValue) -> Union["CelValue", None]:
    """Convert a Python value to a CEL-compatible type.

    Args:
        value: A Python value (None, bool, int, float, str, list, or dict)

    Returns:
        The corresponding CEL type, or None if input is None
    """
    if value is None:
        return None

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

    # Fallback for any other type - convert to string
    return celtypes.StringType(str(value))


def _build_step_input_context(
    step_input: "StepInput",  # type: ignore  # noqa: F821
    session_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build context for CEL evaluation of step input.

    Maps directly to StepInput fields:
        - input: from step_input.input (as string)
        - previous_step_content: from step_input.previous_step_content (as string)
        - previous_step_outputs: from step_input.previous_step_outputs (map of step name -> content string)
        - additional_data: from step_input.additional_data
        - session_state: passed separately
    """
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

    previous_step_outputs: Dict[str, str] = {}
    if step_input.previous_step_outputs:
        for name, output in step_input.previous_step_outputs.items():
            previous_step_outputs[name] = str(output.content) if output.content else ""

    return {
        "input": input_str,
        "previous_step_content": previous_content,
        "previous_step_outputs": previous_step_outputs,
        "additional_data": step_input.additional_data or {},
        "session_state": session_state or {},
    }


def _build_loop_step_output_context(
    iteration_results: "List[StepOutput]",  # type: ignore  # noqa: F821
    current_iteration: int = 0,
    max_iterations: int = 3,
) -> Dict[str, Any]:
    """Build context for CEL evaluation of loop end condition from iteration results.

    Maps to StepOutput fields:
        - step_outputs: map of StepOutput.step_name -> str(StepOutput.content)
        - all_success: derived from StepOutput.success
        - last_step_content: content from the last StepOutput of the current loop iteration
    """
    all_success = True
    outputs: Dict[str, str] = {}
    last_content = ""

    for result in iteration_results:
        content = str(result.content) if result.content else ""
        name = result.step_name or f"step_{len(outputs)}"
        outputs[name] = content
        last_content = content
        if not result.success:
            all_success = False

    return {
        "current_iteration": current_iteration,
        "max_iterations": max_iterations,
        "all_success": all_success,
        "last_step_content": last_content,
        "step_outputs": outputs,
    }
