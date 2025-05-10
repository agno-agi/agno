from functools import update_wrapper, wraps
from typing import Any, Callable, Dict, List, Optional, TypeVar, Union, overload

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
    instructions: Optional[str] = None,
    add_instructions: bool = True,
    sanitize_arguments: Optional[bool] = None,
    show_result: Optional[bool] = None,
    stop_after_tool_call: Optional[bool] = None,
    pre_hook: Optional[Callable] = None,
    post_hook: Optional[Callable] = None,
    tool_hooks: Optional[List[Callable]] = None,
    cache_results: bool = False,
    cache_dir: Optional[str] = None,
    cache_ttl: int = 3600,
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
        instructions: Optional[str] - Instructions for using the tool
        add_instructions: bool - If True, add instructions to the system message
        show_result: Optional[bool] - If True, shows the result after function call
        stop_after_tool_call: Optional[bool] - If True, the agent will stop after the function call.
        pre_hook: Optional[Callable] - Hook that runs before the function is executed (deprecated, use tool_execution_hook instead).
        post_hook: Optional[Callable] - Hook that runs after the function is executed (deprecated, use tool_execution_hook instead).
        tool_hooks: Optional[List[Callable]] - List of hooks that run before and after the function is executed.
        cache_results: bool - If True, enable caching of function results
        cache_dir: Optional[str] - Directory to store cache files
        cache_ttl: int - Time-to-live for cached results in seconds

    Returns:
        Union[Function, Callable[[F], Function]]: Decorated function or decorator

    Examples:
        @tool
        def my_function():
            pass

        @tool(name="custom_name", description="Custom description")
        def another_function():
            pass

        @tool
        async def my_async_function():
            pass
    """
    # Move valid kwargs to a frozen set at module level
    VALID_KWARGS = frozenset(
        {
            "name",
            "description",
            "strict",
            "instructions",
            "add_instructions",
            "sanitize_arguments",
            "show_result",
            "stop_after_tool_call",
            "pre_hook",
            "post_hook",
            "tool_hooks",
            "cache_results",
            "cache_dir",
            "cache_ttl",
        }
    )

    # Improve error message with more context
    invalid_kwargs = set(kwargs.keys()) - VALID_KWARGS
    if invalid_kwargs:
        raise ValueError(
            f"Invalid tool configuration arguments: {invalid_kwargs}. Valid arguments are: {sorted(VALID_KWARGS)}"
        )

    def decorator(func: F) -> Function:
        from inspect import getdoc, isasyncgenfunction, iscoroutine, iscoroutinefunction

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.error(
                    f"Error in tool {func.__name__!r}: {e!r}",
                    exc_info=True,
                )
                raise

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                logger.error(
                    f"Error in async tool {func.__name__!r}: {e!r}",
                    exc_info=True,
                )
                raise

        @wraps(func)
        async def async_gen_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.error(
                    f"Error in async generator tool {func.__name__!r}: {e!r}",
                    exc_info=True,
                )
                raise

        # Choose appropriate wrapper based on function type
        if isasyncgenfunction(func):
            wrapper = async_gen_wrapper
        elif iscoroutinefunction(func) or iscoroutine(func):
            wrapper = async_wrapper
        else:
            wrapper = sync_wrapper

        # Preserve the original signature and metadata
        update_wrapper(wrapper, func)

        # Create Function instance with any provided kwargs
        tool_config = {
            "name": kwargs.get("name", func.__name__),
            "description": kwargs.get("description", getdoc(func)),  # Get docstring if description not provided
            "instructions": kwargs.get("instructions"),
            "add_instructions": kwargs.get("add_instructions", True),
            "entrypoint": wrapper,
            "cache_results": kwargs.get("cache_results", False),
            "cache_dir": kwargs.get("cache_dir"),
            "cache_ttl": kwargs.get("cache_ttl", 3600),
            **{
                k: v
                for k, v in kwargs.items()
                if k
                not in [
                    "name",
                    "description",
                    "instructions",
                    "add_instructions",
                    "cache_results",
                    "cache_dir",
                    "cache_ttl",
                ]
                and v is not None
            },
        }
        return Function(**tool_config)

    # Handle both @tool and @tool() cases
    if len(args) == 1 and callable(args[0]) and not kwargs:
        return decorator(args[0])

    return decorator
