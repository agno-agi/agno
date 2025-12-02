from functools import wraps
from typing import Any, Callable, TypeVar, Union, overload

# Type variable for better type hints
F = TypeVar("F", bound=Callable[..., Any])

# Attribute name used to mark hooks for background execution
HOOK_RUN_IN_BACKGROUND_ATTR = "_agno_run_in_background"


def _is_async_function(func: Callable) -> bool:
    """
    Check if a function is async, even when wrapped by decorators like @staticmethod.
    """
    from inspect import iscoroutine, iscoroutinefunction

    # First, try the standard inspect functions
    if iscoroutinefunction(func) or iscoroutine(func):
        return True

    # If the function has a __wrapped__ attribute, check the original function
    if hasattr(func, "__wrapped__"):
        original_func = func.__wrapped__
        if iscoroutinefunction(original_func) or iscoroutine(original_func):
            return True

    # Check if the function has CO_COROUTINE flag in its code object
    try:
        if hasattr(func, "__code__") and func.__code__.co_flags & 0x80:  # CO_COROUTINE flag
            return True
    except (AttributeError, TypeError):
        pass

    return False


@overload
def hook() -> Callable[[F], F]: ...


@overload
def hook(
    *,
    run_in_background: bool = False,
) -> Callable[[F], F]: ...


@overload
def hook(func: F) -> F: ...


def hook(*args, **kwargs) -> Union[F, Callable[[F], F]]:
    """Decorator to configure hook behavior.

    Args:
        run_in_background: If True, this hook will be scheduled as a FastAPI background task
                          when background_tasks is available, regardless of the agent/team's
                          run_hooks_in_background setting. This allows per-hook control over
                          background execution.

    Returns:
        Union[F, Callable[[F], F]]: Decorated function or decorator

    Examples:
        @hook
        def my_hook(run_output, agent):
            # This runs normally (blocking)
            process_output(run_output.content)

        @hook()
        def another_hook(run_output, agent):
            # Same as above - runs normally
            process_output(run_output.content)

        @hook(run_in_background=True)
        def my_background_hook(run_output, agent):
            # This will run in the background when background_tasks is available
            send_notification(run_output.content)

        @hook(run_in_background=True)
        async def my_async_background_hook(run_output, agent):
            # Async hooks also supported
            await send_async_notification(run_output.content)

        agent = Agent(
            model=OpenAIChat(id="gpt-4o"),
            post_hooks=[my_hook, my_background_hook],
        )
    """
    # Valid kwargs for the hook decorator
    VALID_KWARGS = frozenset({"run_in_background"})

    # Validate kwargs
    invalid_kwargs = set(kwargs.keys()) - VALID_KWARGS
    if invalid_kwargs:
        raise ValueError(
            f"Invalid hook configuration arguments: {invalid_kwargs}. "
            f"Valid arguments are: {sorted(VALID_KWARGS)}"
        )

    def decorator(func: F) -> F:
        run_in_background = kwargs.get("run_in_background", False)

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            return await func(*args, **kwargs)

        # Choose appropriate wrapper based on function type
        if _is_async_function(func):
            wrapper = async_wrapper
        else:
            wrapper = sync_wrapper

        # Set the background execution attribute
        setattr(wrapper, HOOK_RUN_IN_BACKGROUND_ATTR, run_in_background)

        return wrapper  # type: ignore

    # Handle both @hook and @hook() cases
    if len(args) == 1 and callable(args[0]) and not kwargs:
        return decorator(args[0])

    return decorator


def should_run_in_background(hook_func: Callable) -> bool:
    """
    Check if a hook function is marked to run in background.

    Args:
        hook_func: The hook function to check

    Returns:
        True if the hook is decorated with @hook(run_in_background=True)
    """
    return getattr(hook_func, HOOK_RUN_IN_BACKGROUND_ATTR, False)
