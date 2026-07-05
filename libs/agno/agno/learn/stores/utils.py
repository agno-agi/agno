from typing import Any, Callable, List

from agno.tools.function import Function
from agno.utils.log import log_debug, log_warning


def build_functions_for_model(tools: List[Callable], model: Any, *, log_added: bool = False) -> List[Function]:
    """Convert learning store callables to Functions for the configured model."""
    functions: List[Function] = []
    seen_names = set()
    use_strict_tools = bool(getattr(model, "supports_native_structured_outputs", False))

    for tool in tools:
        try:
            name = tool.__name__
            if name in seen_names:
                continue
            seen_names.add(name)

            func = Function.from_callable(tool, strict=use_strict_tools)
            if use_strict_tools:
                func.strict = True
            functions.append(func)
            if log_added:
                log_debug(f"Added function {func.name}")
        except Exception as e:
            log_warning(f"Could not add function {tool}: {str(e)}")

    return functions
