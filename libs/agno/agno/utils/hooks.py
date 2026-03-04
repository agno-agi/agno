from copy import deepcopy
from typing import Any, Callable, Dict, List, Optional, Union

from agno.eval.base import BaseEval
from agno.guardrails.base import BaseGuardrail
from agno.hooks.decorator import HOOK_RUN_IN_BACKGROUND_ATTR
from agno.utils.log import log_warning

# Keys that should be deep copied for background hooks to prevent race conditions
BACKGROUND_HOOK_COPY_KEYS = frozenset(
    {"run_input", "run_context", "run_output", "session_state", "dependencies", "metadata"}
)


def copy_args_for_background(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a copy of hook arguments for background execution.

    This deep copies run_input, run_context, run_output, session_state, dependencies,
    and metadata to prevent race conditions when hooks run in the background.

    Args:
        args: The original arguments dictionary

    Returns:
        A new dictionary with copied values for sensitive keys
    """
    copied_args = {}
    for key, value in args.items():
        if key in BACKGROUND_HOOK_COPY_KEYS and value is not None:
            try:
                copied_args[key] = deepcopy(value)
            except Exception:
                # If deepcopy fails (e.g., for non-copyable objects), use the original
                log_warning(f"Could not deepcopy {key} for background hook, using original reference")
                copied_args[key] = value
        else:
            copied_args[key] = value
    return copied_args


def should_run_hook_in_background(hook: Callable[..., Any]) -> bool:
    """
    Check if a hook function should run in background.

    This checks for the _agno_run_in_background attribute set by the @hook decorator.

    Args:
        hook: The hook function to check

    Returns:
        True if the hook is decorated with @hook(run_in_background=True)
    """
    return getattr(hook, HOOK_RUN_IN_BACKGROUND_ATTR, False)


def is_guardrail_hook(hook: Callable[..., Any]) -> bool:
    """Check if a hook was derived from a BaseGuardrail instance.

    Guardrails are converted to bound methods (.check/.async_check) by normalize_pre_hooks().
    They must always run synchronously so InputCheckError/OutputCheckError can propagate.
    """
    # TODO: Replace __self__ introspection with a NormalizedHook(fn, kind) wrapper
    # so classification happens once at normalization time, not at execution time.
    # The current approach works because normalize_pre_hooks() always produces bound
    # methods, but would break if hooks are wrapped with decorators or functools.partial.
    return hasattr(hook, "__self__") and isinstance(hook.__self__, BaseGuardrail)


def normalize_pre_hooks(
    hooks: Optional[List[Union[Callable[..., Any], BaseGuardrail, BaseEval]]],
    async_mode: bool = False,
) -> Optional[List[Callable[..., Any]]]:
    """Normalize pre-hooks to a list format.

    Args:
        hooks: List of hook functions, guardrails, or eval instances
        async_mode: Whether to use async versions of methods
    """
    result_hooks: List[Callable[..., Any]] = []

    if hooks is not None:
        for hook in hooks:
            if isinstance(hook, BaseGuardrail):
                if async_mode:
                    result_hooks.append(hook.async_check)
                else:
                    result_hooks.append(hook.check)
            elif isinstance(hook, BaseEval):
                # Extract pre_check method
                method = hook.async_pre_check if async_mode else hook.pre_check

                from functools import partial

                wrapped = partial(method)
                wrapped.__name__ = method.__name__  # type: ignore
                setattr(wrapped, HOOK_RUN_IN_BACKGROUND_ATTR, getattr(hook, "run_in_background", False))
                result_hooks.append(wrapped)
            else:
                # Check if the hook is async and used within sync methods
                if not async_mode:
                    import asyncio

                    if asyncio.iscoroutinefunction(hook):
                        raise ValueError(
                            f"Cannot use {hook.__name__} (an async hook) with `run()`. Use `arun()` instead."
                        )

                result_hooks.append(hook)
    return result_hooks if result_hooks else None


def normalize_post_hooks(
    hooks: Optional[List[Union[Callable[..., Any], BaseGuardrail, BaseEval]]],
    async_mode: bool = False,
) -> Optional[List[Callable[..., Any]]]:
    """Normalize post-hooks to a list format.

    Args:
        hooks: List of hook functions, guardrails, or eval instances
        async_mode: Whether to use async versions of methods
    """
    result_hooks: List[Callable[..., Any]] = []

    if hooks is not None:
        for hook in hooks:
            if isinstance(hook, BaseGuardrail):
                if async_mode:
                    result_hooks.append(hook.async_check)
                else:
                    result_hooks.append(hook.check)
            elif isinstance(hook, BaseEval):
                # Extract post_check method
                method = hook.async_post_check if async_mode else hook.post_check  # type: ignore[assignment]

                from functools import partial

                wrapped = partial(method)
                wrapped.__name__ = method.__name__  # type: ignore
                setattr(wrapped, HOOK_RUN_IN_BACKGROUND_ATTR, getattr(hook, "run_in_background", False))
                result_hooks.append(wrapped)
            else:
                # Check if the hook is async and used within sync methods
                if not async_mode:
                    import asyncio

                    if asyncio.iscoroutinefunction(hook):
                        raise ValueError(
                            f"Cannot use {hook.__name__} (an async hook) with `run()`. Use `arun()` instead."
                        )

                result_hooks.append(hook)
    return result_hooks if result_hooks else None


def filter_hook_args(hook: Callable[..., Any], all_args: Dict[str, Any]) -> Dict[str, Any]:
    """Filter arguments to only include those that the hook function accepts."""
    import inspect

    try:
        sig = inspect.signature(hook)
        accepted_params = set(sig.parameters.keys())

        has_var_keyword = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in sig.parameters.values())

        # If the function has **kwargs, pass all arguments
        if has_var_keyword:
            return all_args

        # Otherwise, filter to only include accepted parameters
        filtered_args = {key: value for key, value in all_args.items() if key in accepted_params}

        return filtered_args

    except Exception as e:
        log_warning(f"Could not inspect hook signature, passing all arguments: {e}")
        # If signature inspection fails, pass all arguments as fallback
        return all_args
