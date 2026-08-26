"""Handle- and parameter-name derivation for kernel-side bindings."""

from __future__ import annotations

import keyword
import re
from typing import Any, Callable, Collection, List, Sequence, Union

from agno.tools.function import Function
from agno.tools.toolkit import Toolkit

_HANDLE_SUFFIX = "_tools"


def derive_handle_name(name: str, taken: Collection[str] = ()) -> str:
    """Derive the kernel-side handle for a toolkit name.

    A trailing ``_tools`` is stripped (``arcade_tools`` binds as ``arcade``),
    then the result is coerced to a valid Python identifier. A handle already
    taken by an earlier binding gets a numeric suffix: two toolkits reducing
    to one name would otherwise silently shadow each other in the kernel.
    """
    base = name
    if base.endswith(_HANDLE_SUFFIX) and len(base) > len(_HANDLE_SUFFIX):
        base = base[: -len(_HANDLE_SUFFIX)]
    handle = re.sub(r"\W", "_", base)
    if not handle or handle[0].isdigit():
        handle = "_" + handle
    if handle not in taken:
        return handle
    suffix = 2
    while f"{handle}_{suffix}" in taken:
        suffix += 1
    return f"{handle}_{suffix}"


def safe_param_name(name: str, taken: Collection[str] = ()) -> str:
    """A valid Python parameter name for a JSON-schema property name.

    Schema property names carry no Python constraints: ``from`` is a keyword,
    ``start-date`` is not an identifier, and either one makes
    ``inspect.Parameter`` raise. Non-identifier characters become underscores,
    a leading digit and an empty name get a leading underscore, a keyword gets
    a trailing one, and a name already used by an earlier parameter of the same
    function gets a numeric suffix. The kernel stub maps the result back to the
    schema name before the call leaves the kernel.
    """
    candidate = re.sub(r"\W", "_", name or "")
    if not candidate or candidate[0].isdigit():
        candidate = "_" + candidate
    if keyword.iskeyword(candidate):
        candidate = candidate + "_"
    if candidate not in taken:
        return candidate
    suffix = 2
    while f"{candidate}_{suffix}" in taken:
        suffix += 1
    return f"{candidate}_{suffix}"


def handle_names_for(tools: Sequence[Union[Toolkit, Callable[..., Any], Function]]) -> List[str]:
    """The kernel-side names the given tools bind under, in input order.

    A tool name carries no Python constraints — an MCP server may call a tool
    ``get-forecast`` — and the bridge binds it under a name a cell can
    reference, so these are the adapted names, not the tools' own. Toolkits
    and top-level callables share one kernel namespace, so the names are
    deduplicated across all of them, in input order, the same way the bridge
    binds them. 'results' is reserved for the built-in stored-results handle,
    so a toolkit reducing to that name binds under a suffix.
    """
    names: List[str] = []
    taken: List[str] = ["results"]
    for tool in tools:
        if isinstance(tool, Toolkit):
            names.append(derive_handle_name(tool.name, taken))
        elif isinstance(tool, Function):
            names.append(safe_param_name(tool.name, taken))
        else:
            names.append(safe_param_name(getattr(tool, "__name__", str(tool)), taken))
        taken.append(names[-1])
    return names
