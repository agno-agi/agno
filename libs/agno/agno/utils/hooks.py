from typing import Any, Callable, Dict, List, Optional, Union

from agno.guardrails.base import BaseGuardrail
from agno.utils.log import log_warning


def normalize_hooks(
    hooks: Optional[Union[List[Callable[..., Any]], List[BaseGuardrail]]],
    async_mode: bool = False,
) -> Optional[List[Callable[..., Any]]]:
    """Normalize hooks to a list format"""
    result_hooks: List[Callable[..., Any]] = []

    if hooks is not None:
        for hook in hooks:
            if isinstance(hook, BaseGuardrail):
                if async_mode:
                    result_hooks.append(hook.async_check)
                else:
                    result_hooks.append(hook.check)
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
