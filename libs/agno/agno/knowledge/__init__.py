"""Knowledge package.

The public classes resolve on first access (PEP 562) so importing a leaf
module such as ``agno.knowledge.types`` does not load the readers, the
remote-content backends and their cloud clients.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agno.knowledge.filesystem import FileSystemKnowledge
    from agno.knowledge.knowledge import Knowledge
    from agno.knowledge.protocol import KnowledgeProtocol

__all__ = [
    "FileSystemKnowledge",
    "Knowledge",
    "KnowledgeProtocol",
]

_LAZY_ATTRS = {
    "FileSystemKnowledge": "agno.knowledge.filesystem",
    "Knowledge": "agno.knowledge.knowledge",
    "KnowledgeProtocol": "agno.knowledge.protocol",
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
