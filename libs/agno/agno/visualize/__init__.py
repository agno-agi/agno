"""Visualization tools for Agno workflows (and in future, teams).

Generate Mermaid diagrams with export to SVG, PNG, and on-screen display.

Core Mermaid text generation is pure Python with zero extra dependencies.
SVG/PNG rendering uses the mermaid.ink API via ``httpx`` (a core dep).
``show()`` additionally requires ``Pillow``.
"""

from agno.visualize._renderer import DEFAULT_INK_SERVER, WorkflowVisualization
from agno.visualize._themes import AVAILABLE_FLAVORS
from agno.visualize.workflow import generate_mermaid

__all__ = [
    "AVAILABLE_FLAVORS",
    "DEFAULT_INK_SERVER",
    "WorkflowVisualization",
    "generate_mermaid",
]
