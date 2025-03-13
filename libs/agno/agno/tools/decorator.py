from functools import update_wrapper, wraps
from typing import Any, Callable, Dict, Optional, TypeVar, Union, overload

from agno.tools.function import Function
from agno.utils.log import logger

# Type variable for better type hints
F = TypeVar("F", bound=Callable[..., Any])
ToolConfig = TypeVar("ToolConfig", bound=Dict[str, Any])


@overload
def tool() -> Callable[[F], Function]: ...


@overload
def tool(
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    strict: Optional[bool] = None,
    sanitize_arguments: Optional[bool] = None,
    show_result: Optional[bool] = None,
    stop_after_call: Optional[bool] = None,
    pre_hook: Optional[Callable] = None,
    post_hook: Optional[Callable] = None,
) -> Callable[[F], Function]: ...


@overload
def tool(func: F) -> Function: ...


def tool(*args, **kwargs) -> Union[Function, Callable[[F], Function]]:
    """Decorator to convert a function into a Function that can be used by an agent.

    Args:
        name: Optional[str] - Override for the function name
        description: Optional[str] - Override for the function description
        strict: Optional[bool] - Flag for strict parameter checking
        sanitize_arguments: Optional[bool] - If True, arguments are sanitized before passing to function
        show_result: Optional[bool] - If True, shows the result after function call
        stop_after_call: Optional[bool] - If True, the agent will stop after the function call.
        pre_hook: Optional[Callable] - Hook that runs before the function is executed.
        post_hook: Optional[Callable] - Hook that runs after the function is executed.

    Returns:
        Union[Function, Callable[[F], Function]]: Decorated function or decorator

    Examples:
        @tool
        def my_function():
            pass

        @tool(name="custom_name", description="Custom description")
        def another_function():
            pass
    """
    # Move valid kwargs to a frozen set at module level
    VALID_KWARGS = frozenset(
        {
            "name",
            "description",
            "strict",
            "sanitize_arguments",
            "show_result",
            "stop_after_call",
            "pre_hook",
            "post_hook",
        }
    )

    # Improve error message with more context
    invalid_kwargs = set(kwargs.keys()) - VALID_KWARGS
    if invalid_kwargs:
        raise ValueError(
            f"Invalid tool configuration arguments: {invalid_kwargs}. Valid arguments are: {sorted(VALID_KWARGS)}"
        )

    def decorator(func: F) -> Function:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.error(
                    f"Error in tool {func.__name__!r}: {e!r}",
                    exc_info=True,  # Include stack trace
                )
                raise

        # Preserve the original signature
        update_wrapper(wrapper, func)

        # Create Function instance with any provided kwargs
        tool_config = {
            "name": kwargs.get("name", func.__name__),
            "entrypoint": wrapper,
            **{k: v for k, v in kwargs.items() if k != "name" and v is not None},
        }
        return Function(**tool_config)

    # Handle both @tool and @tool() cases
    if len(args) == 1 and callable(args[0]) and not kwargs:
        return decorator(args[0])

    return decorator
