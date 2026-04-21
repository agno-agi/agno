"""
Context Providers
=================

Expose any external source — the web, a filesystem, Slack, GitHub, Drive,
an MCP server — to an agent as a first-class, queryable context.

Every source subclasses :class:`ContextProvider`. A :class:`ContextBackend`
is the pluggable I/O layer behind a provider (used today by
:class:`agno.context.web.WebContextProvider`).
"""

from agno.context.backend import ContextBackend
from agno.context.mode import ContextMode
from agno.context.provider import (
    Answer,
    ContextProvider,
    Document,
    Status,
)

__all__ = [
    "Answer",
    "ContextBackend",
    "ContextMode",
    "ContextProvider",
    "Document",
    "Status",
]
