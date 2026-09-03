"""Knowledge toolkits.

``KnowledgeTools`` is the read side — think, search, analyze — for product agents.
``KnowledgeManagementTools`` is the write side — ingest, list, remove — for builder and
operator agents, so widening one never leaks write capability into the other.

Both resolve on first access (PEP 562).
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agno.tools.knowledge.knowledge import KnowledgeTools
    from agno.tools.knowledge.management import KnowledgeManagementTools

__all__ = [
    "KnowledgeManagementTools",
    "KnowledgeTools",
]

_LAZY_ATTRS = {
    "KnowledgeManagementTools": "agno.tools.knowledge.management",
    "KnowledgeTools": "agno.tools.knowledge.knowledge",
}


def __getattr__(name: str) -> Any:
    module_name = _LAZY_ATTRS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list:
    return sorted(set(globals()) | set(__all__))
