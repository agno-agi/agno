"""Handle-name derivation for kernel-side bindings."""

from __future__ import annotations

import re
from typing import Any, Callable, List, Sequence, Union

from agno.tools.function import Function
from agno.tools.toolkit import Toolkit

_HANDLE_SUFFIX = "_tools"


def derive_handle_name(name: str) -> str:
    """Derive the kernel-side handle for a toolkit name.

    A trailing ``_tools`` is stripped (``arcade_tools`` binds as ``arcade``),
    then the result is coerced to a valid Python identifier.
    """
    base = name
    if base.endswith(_HANDLE_SUFFIX) and len(base) > len(_HANDLE_SUFFIX):
        base = base[: -len(_HANDLE_SUFFIX)]
    handle = re.sub(r"\W", "_", base)
    if not handle or handle[0].isdigit():
        handle = "_" + handle
    return handle


def handle_names_for(tools: Sequence[Union[Toolkit, Callable[..., Any], Function]]) -> List[str]:
    """The kernel-side names the given tools bind under, in input order."""
    names: List[str] = []
    for tool in tools:
        if isinstance(tool, Toolkit):
            names.append(derive_handle_name(tool.name))
        elif isinstance(tool, Function):
            names.append(tool.name)
        else:
            names.append(getattr(tool, "__name__", str(tool)))
    return names
