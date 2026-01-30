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
    step_choices: Optional[List[str]] = None,
) -> bool:
    """Evaluate a CEL expression for a Condition evaluator.

    Context variables:
        - input: The workflow input as a string
        - previous_step_content: Content from the previous step
        - has_previous_step_content: Whether previous content exists
        - previous_step_contents: List of content strings from all previous steps
        - all_previous_content: Concatenated content from all previous steps (formatted)
        - additional_data: Map of additional data passed to the workflow
        - session_state: Map of session state values
        - step_choices: List of step names available to the selector
    """
    context = _build_step_input_context(step_input, session_state)
    context["step_choices"] = step_choices or []
    return _evaluate_cel(expression, context)


def evaluate_cel_loop_end_condition(
    expression: str,
    iteration_results: "List[StepOutput]",  # type: ignore  # noqa: F821
    iteration: int = 0,
    max_iterations: int = 3,
) -> bool:
    """Evaluate a CEL expression as a Loop end condition.

    Context variables:
        - iteration: Current iteration number (0-indexed)
        - max_iterations: Maximum iterations configured for the loop
        - num_steps: Number of step outputs in the current iteration
        - all_success: True if all steps succeeded
        - any_failure: True if any step failed
        - step_contents: List of content strings from all steps in order
        - first_step_content: Content string from the first step
        - last_step_content: Content string from the last step
        - total_content_length: Sum of all step content lengths
        - max_content_length: Length of the longest step content
    """
    return _evaluate_cel(expression, _build_loop_step_output_context(iteration_results, iteration, max_iterations))


def evaluate_cel_router_selector(
    expression: str,
    step_input: "StepInput",  # type: ignore  # noqa: F821
    session_state: Optional[Dict[str, Any]] = None,
    step_choices: Optional[List[str]] = None,
) -> str:
    """Evaluate a CEL expression for a Router selector.

    Returns the name of the step to execute as a string.

    Context variables (same as Condition):
        - input: The workflow input as a string
        - previous_step_content: Content from the previous step
        - has_previous_step_content: Whether previous content exists
        - previous_step_contents: List of content strings from all previous steps
        - all_previous_content: Concatenated content from all previous steps (formatted)
        - additional_data: Map of additional data passed to the workflow
        - session_state: Map of session state values

    Example CEL expressions:
        - 'input.contains("video") ? "video_step" : "image_step"'
        - 'additional_data.route'
        - 'session_state.preferred_handler'
    """
    context = _build_step_input_context(step_input, session_state)
    context["step_choices"] = step_choices or []
    return _evaluate_cel_string(expression, context)


# ********** Internal Functions **********
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


def _to_cel(value: PythonValue) -> Union[CelValue, None]:
    """Convert a Python value to a CEL-compatible type.
    
    Args:
        value: A Python value (None, bool, int, float, str, list, or dict)
        
    Returns:
        The corresponding CEL type, or None if input is None
    """
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

    # Fallback for any other type - convert to string
    return celtypes.StringType(str(value))


def _build_step_input_context(
    step_input: "StepInput",  # type: ignore  # noqa: F821
    session_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build context for CEL evaluation of step input."""
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

    previous_step_contents: List[str] = []
    if step_input.previous_step_outputs:
        previous_step_contents = [str(output.content) for output in step_input.previous_step_outputs.values()]

    # Build all_previous_content similar to StepInput.get_all_previous_content()
    all_previous_content = ""
    if step_input.previous_step_outputs:
        content_parts = []
        for name, output in step_input.previous_step_outputs.items():
            if output.content:
                content_parts.append(f"=== {name} ===\n{output.content}")
        all_previous_content = "\n\n".join(content_parts)

    return {
        "input": input_str,
        "previous_step_content": previous_content,
        "has_previous_step_content": bool(step_input.previous_step_content),
        "previous_step_contents": previous_step_contents,
        "all_previous_content": all_previous_content,
        "additional_data": step_input.additional_data or {},
        "session_state": session_state or {},
    }


def _build_loop_step_output_context(
    iteration_results: "List[StepOutput]",  # type: ignore  # noqa: F821
    iteration: int = 0,
    max_iterations: int = 3,
) -> Dict[str, Any]:
    """Build context for CEL evaluation of loop end condition from iteration results."""
    all_success = True
    any_failure = False
    total_content_length = 0
    max_content_length = 0
    contents: List[str] = []

    for result in iteration_results:
        content = str(result.content) if result.content else ""
        contents.append(content)
        content_len = len(content)
        total_content_length += content_len
        if content_len > max_content_length:
            max_content_length = content_len
        if not result.success:
            all_success = False
            any_failure = True

    last_content = contents[-1] if contents else ""

    return {
        "iteration": iteration,
        "max_iterations": max_iterations,
        "num_steps": len(iteration_results),
        "all_success": all_success,
        "any_failure": any_failure,
        "step_contents": contents,
        "last_step_content": last_content,
        "total_content_length": total_content_length,
        "max_content_length": max_content_length,
    }
