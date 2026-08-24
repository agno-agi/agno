from functools import wraps
from typing import Any, Callable, TypeVar, Union, overload

# Type variable for better type hints
F = TypeVar("F", bound=Callable[..., Any])

# Attribute name used to mark hooks for background execution
HOOK_RUN_IN_BACKGROUND_ATTR = "_agno_run_in_background"
# Attribute name used to mark hooks that should run on continue_run
HOOK_RUN_ON_CONTINUE_ATTR = "_agno_run_on_continue"


def _is_async_function(func: Callable) -> bool:
    """
    Check if a function is async, even when wrapped by decorators like @staticmethod.
    Traverses the full wrapper chain to find the original function.
    """
    from inspect import iscoroutinefunction, unwrap

    # First, try the standard inspect function on the wrapper
    if iscoroutinefunction(func):
        return True

    # Use unwrap to traverse the full __wrapped__ chain to the original function
    try:
        original_func = unwrap(func)
        if original_func is not func and iscoroutinefunction(original_func):
            return True
    except ValueError:
        # unwrap raises ValueError if it hits a cycle
        pass

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
    run_on_continue: bool = False,
) -> Callable[[F], F]: ...


@overload
def hook(func: F) -> F: ...


def hook(*args, **kwargs) -> Union[F, Callable[[F], F]]:
    """Decorator to configure hook behavior.

    Args:
        run_in_background: If True, this hook will be scheduled as a FastAPI background task
                          when background_tasks is available, regardless of the agent/team's
                          run_hooks_in_background setting. This allows per-hook control over
                          background execution. This is only usable when running with AgentOS.
        run_on_continue: If True, this hook will also run on continue_run() calls.
                        By default (False), hooks only run on initial run() calls and are
                        skipped on continue_run() since the input was already validated.
                        Set to True for security-critical hooks that must run on every
                        execution boundary.

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

        @hook(run_on_continue=True)
        def security_hook(run_input, agent):
            # This hook runs on BOTH run() and continue_run()
            validate_permissions(run_input)

        agent = Agent(
            model=OpenAIChat(id="gpt-5.5"),
            post_hooks=[my_hook, my_background_hook],
        )
    """
    # Valid kwargs for the hook decorator
    VALID_KWARGS = frozenset({"run_in_background", "run_on_continue"})

    # Validate kwargs
    invalid_kwargs = set(kwargs.keys()) - VALID_KWARGS
    if invalid_kwargs:
        raise ValueError(
            f"Invalid hook configuration arguments: {invalid_kwargs}. Valid arguments are: {sorted(VALID_KWARGS)}"
        )

    def decorator(func: F) -> F:
        run_in_background = kwargs.get("run_in_background", False)
        run_on_continue = kwargs.get("run_on_continue", False)

        # Preserve existing hook attributes from previously applied decorators
        # Use OR logic: if any decorator sets run_in_background=True, it stays True
        existing_run_in_background = should_run_in_background(func)
        existing_run_on_continue = should_run_on_continue(func)
        final_run_in_background = run_in_background or existing_run_in_background
        final_run_on_continue = run_on_continue or existing_run_on_continue

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

        # Set the hook attributes (combined from all decorators)
        setattr(wrapper, HOOK_RUN_IN_BACKGROUND_ATTR, final_run_in_background)
        setattr(wrapper, HOOK_RUN_ON_CONTINUE_ATTR, final_run_on_continue)

        return wrapper  # type: ignore

    # Handle both @hook and @hook() cases
    if len(args) == 1 and callable(args[0]) and not kwargs:
        return decorator(args[0])

    return decorator


def _get_hook_attr(hook_func: Callable, attr_name: str, default: bool = False) -> bool:
    """
    Get a hook attribute, traversing the wrapper chain if needed.

    Args:
        hook_func: The hook function to check
        attr_name: The attribute name to look for
        default: Default value if attribute not found

    Returns:
        The attribute value, or default if not found
    """
    # Check the function directly first
    if hasattr(hook_func, attr_name):
        return getattr(hook_func, attr_name)

    # Traverse the wrapper chain to find the attribute
    current = hook_func
    seen: set[int] = set()
    while hasattr(current, "__wrapped__"):
        if id(current) in seen:
            break
        seen.add(id(current))
        current = current.__wrapped__
        if hasattr(current, attr_name):
            return getattr(current, attr_name)

    return default


def should_run_in_background(hook_func: Callable) -> bool:
    """
    Check if a hook function is marked to run in background.

    Args:
        hook_func: The hook function to check

    Returns:
        True if the hook is decorated with @hook(run_in_background=True)
    """
    return _get_hook_attr(hook_func, HOOK_RUN_IN_BACKGROUND_ATTR, False)


def should_run_on_continue(hook_func: Callable) -> bool:
    """
    Check if a hook function should run on continue_run().

    Args:
        hook_func: The hook function to check

    Returns:
        True if the hook is decorated with @hook(run_on_continue=True)
    """
    return _get_hook_attr(hook_func, HOOK_RUN_ON_CONTINUE_ATTR, False)
