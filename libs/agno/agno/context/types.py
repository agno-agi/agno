from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Status:
    """Health of a context provider."""

    ok: bool
    detail: str = ""


@dataclass
class Document:
    """A piece of content available through a provider."""

    id: str
    name: str
    uri: str | None = None
    source: str | None = None
    snippet: str | None = None


@dataclass
class Answer:
    """What query() returns."""

    results: list[Document] = field(default_factory=list)
    text: str | None = None
