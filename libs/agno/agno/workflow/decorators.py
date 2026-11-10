"""Decorators for workflow step configuration."""

from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, TypeVar, Union

F = TypeVar("F", bound=Callable)

if TYPE_CHECKING:
    from agno.workflow.types import UserInputField


def pause(
    name: Optional[str] = None,
    requires_confirmation: bool = False,
    confirmation_message: Optional[str] = None,
    requires_user_input: bool = False,
    user_input_message: Optional[str] = None,
    user_input_schema: Optional[List[Union[Dict[str, Any], "UserInputField"]]] = None,
) -> Callable[[F], F]:
    """Decorator to mark a step function with Human-In-The-Loop (HITL) configuration.

    This decorator adds HITL metadata to a function that will be used as a workflow step.
    When the function is passed to a Step or directly to a Workflow, the HITL configuration
    will be automatically detected and applied.

    Args:
        name: Optional name for the step. If not provided, the function name will be used.
        requires_confirmation: Whether the step requires user confirmation before execution.
            Defaults to False.
        confirmation_message: Message to display to the user when requesting confirmation.
        requires_user_input: Whether the step requires user input before execution.
            Defaults to False.
        user_input_message: Message to display to the user when requesting input.
        user_input_schema: Schema for user input fields. Can be a list of dicts or
            UserInputField objects. Each field should have:
            - name: Field name (required)
            - field_type: "str", "int", "float", "bool" (default: "str")
            - description: Field description (optional)
            - required: Whether field is required (default: True)

    Returns:
        A decorator that adds HITL metadata to the function.
    """

    def decorator(func: F) -> F:
        # Store HITL metadata directly on the function
        func._hitl_name = name  # type: ignore[attr-defined]
        func._hitl_requires_confirmation = requires_confirmation  # type: ignore[attr-defined]
        func._hitl_confirmation_message = confirmation_message  # type: ignore[attr-defined]
        func._hitl_requires_user_input = requires_user_input  # type: ignore[attr-defined]
        func._hitl_user_input_message = user_input_message  # type: ignore[attr-defined]
        func._hitl_user_input_schema = user_input_schema  # type: ignore[attr-defined]

        return func

    return decorator


def get_pause_metadata(func: Callable) -> dict:
    """Extract HITL metadata from a function if it has been decorated with @pause.

    Args:
        func: The function to extract metadata from.

    Returns:
        A dictionary with HITL configuration, or empty dict if not decorated.
    """
    if not callable(func):
        return {}

    metadata = {}

    if hasattr(func, "_hitl_name"):
        metadata["name"] = func._hitl_name  # type: ignore[attr-defined]

    if hasattr(func, "_hitl_requires_confirmation"):
        metadata["requires_confirmation"] = func._hitl_requires_confirmation  # type: ignore[attr-defined]

    if hasattr(func, "_hitl_confirmation_message"):
        metadata["confirmation_message"] = func._hitl_confirmation_message  # type: ignore[attr-defined]

    if hasattr(func, "_hitl_requires_user_input"):
        metadata["requires_user_input"] = func._hitl_requires_user_input  # type: ignore[attr-defined]

    if hasattr(func, "_hitl_user_input_message"):
        metadata["user_input_message"] = func._hitl_user_input_message  # type: ignore[attr-defined]

    if hasattr(func, "_hitl_user_input_schema"):
        metadata["user_input_schema"] = func._hitl_user_input_schema  # type: ignore[attr-defined]

    return metadata


def has_pause_metadata(func: Callable) -> bool:
    """Check if a function has HITL metadata from the @pause decorator.

    Args:
        func: The function to check.

    Returns:
        True if the function has HITL metadata, False otherwise.
    """
    return hasattr(func, "_hitl_requires_confirmation") or hasattr(func, "_hitl_requires_user_input")
