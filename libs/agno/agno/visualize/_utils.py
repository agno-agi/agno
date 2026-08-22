"""Shared utilities for visualization modules."""

from __future__ import annotations


class _IdCounter:
    """Tiny mutable counter shared across recursive calls."""

    def __init__(self) -> None:
        self._n = 0

    def next(self, prefix: str = "n") -> str:
        self._n += 1
        return f"{prefix}{self._n}"


# ---------------------------------------------------------------------------
# Mermaid node shapes per step type
# ---------------------------------------------------------------------------
_SHAPE = {
    "step": ("[", "]"),  # rectangle
    "steps": ("[", "]"),  # rectangle (subgraph handles grouping)
    "condition": ("{", "}"),  # diamond
    "router": ("{", "}"),  # diamond
    "loop": ("([", "])"),  # stadium / rounded
    "parallel": ("([", "])"),  # stadium / rounded
    "callable": ("[/", "/]"),  # trapezoid
    "start": ("([", "])"),  # stadium
    "end": ("([", "])"),  # stadium
}


def _sanitize(text: str) -> str:
    """Escape characters that break Mermaid syntax."""
    return text.replace('"', "#quot;").replace("(", "#lpar;").replace(")", "#rpar;")
