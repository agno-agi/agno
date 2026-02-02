"""Decorators for workflow step configuration."""

from functools import wraps
from typing import Callable, Optional, TypeVar

F = TypeVar("F", bound=Callable)


def hitl(
    name: Optional[str] = None,
    requires_confirmation: bool = True,
    confirmation_message: Optional[str] = None,
) -> Callable[[F], F]:
    """Decorator to mark a step function with Human-In-The-Loop (HITL) configuration.

    This decorator adds HITL metadata to a function that will be used as a workflow step.
    When the function is passed to a Step or directly to a Workflow, the HITL configuration
    will be automatically detected and applied.

    Args:
        name: Optional name for the step. If not provided, the function name will be used.
        requires_confirmation: Whether the step requires user confirmation before execution.
            Defaults to True.
        confirmation_message: Message to display to the user when requesting confirmation.
            If not provided, a default message will be generated.

    Returns:
        A decorator that adds HITL metadata to the function.

    Example:
        ```python
        from agno.workflow.decorators import hitl
        from agno.workflow.types import StepInput, StepOutput

        @hitl(
            name="Process Data",
            requires_confirmation=True,
            confirmation_message="About to process sensitive data. Confirm?"
        )
        def process_data(step_input: StepInput) -> StepOutput:
            # Process data here
            return StepOutput(content="Data processed")

        # Use in workflow - HITL config is auto-detected
        workflow = Workflow(
            steps=[process_data],  # No need to wrap in Step manually
        )

        # Or explicitly wrap in Step - HITL config is still auto-detected
        step = Step(executor=process_data)
        ```
    """

    def decorator(func: F) -> F:
        # Store HITL metadata on the function
        func._hitl_name = name  # type: ignore[attr-defined]
        func._hitl_requires_confirmation = requires_confirmation  # type: ignore[attr-defined]
        func._hitl_confirmation_message = confirmation_message  # type: ignore[attr-defined]

        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        # Copy HITL metadata to wrapper
        wrapper._hitl_name = name  # type: ignore[attr-defined]
        wrapper._hitl_requires_confirmation = requires_confirmation  # type: ignore[attr-defined]
        wrapper._hitl_confirmation_message = confirmation_message  # type: ignore[attr-defined]

        return wrapper  # type: ignore[return-value]

    return decorator


def get_hitl_metadata(func: Callable) -> dict:
    """Extract HITL metadata from a function if it has been decorated with @hitl.

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

    return metadata


def has_hitl_metadata(func: Callable) -> bool:
    """Check if a function has HITL metadata from the @hitl decorator.

    Args:
        func: The function to check.

    Returns:
        True if the function has HITL metadata, False otherwise.
    """
    return hasattr(func, "_hitl_requires_confirmation")
