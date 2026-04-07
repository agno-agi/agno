"""Rendering helpers — convert Mermaid source to SVG, PNG, or display."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional, Union

if TYPE_CHECKING:
    from requests import Response


class WorkflowVisualization:
    """Holds a generated Mermaid diagram and provides export methods.

    * ``to_mermaid()`` — always available (pure Python, no extra deps)
    * ``to_svg(path)`` — requires ``pip install agno[visualize]``
    * ``to_png(path)`` — requires ``pip install agno[visualize]``
    * ``show()`` — opens in default image viewer (requires ``pip install agno[visualize]``)
    """

    def __init__(self, mermaid_text: str, workflow_name: Optional[str] = None) -> None:
        self._mermaid = mermaid_text
        self._workflow_name = workflow_name

    # ------------------------------------------------------------------
    # Pure-Python output (no extra deps)
    # ------------------------------------------------------------------

    def to_mermaid(self) -> str:
        """Return the raw Mermaid flowchart source text."""
        return self._mermaid

    # ------------------------------------------------------------------
    # SVG export
    # ------------------------------------------------------------------

    def to_svg(self, path: Union[str, Path]) -> Path:
        """Render the diagram to an SVG file.

        Args:
            path: Destination file path.

        Returns:
            The resolved ``Path`` that was written.

        Raises:
            ImportError: If ``mermaid-py`` is not installed.
        """
        try:
            import mermaid as md
            from mermaid.graph import Graph
        except ImportError:
            raise ImportError(
                "SVG export requires the mermaid-py package. Install it with: pip install agno[visualize]"
            ) from None

        graph = Graph("workflow", self._mermaid)
        render = md.Mermaid(graph)

        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)

        svg_response = render.svg_response
        if svg_response is None:
            raise RuntimeError("Mermaid rendering returned no SVG data. Check network connectivity to mermaid.ink.")
        resp: Response = svg_response
        svg_text = resp.text
        dest.write_text(svg_text, encoding="utf-8")
        return dest.resolve()

    # ------------------------------------------------------------------
    # PNG export
    # ------------------------------------------------------------------

    def to_png(self, path: Union[str, Path]) -> Path:
        """Render the diagram to a PNG file.

        Args:
            path: Destination file path.

        Returns:
            The resolved ``Path`` that was written.

        Raises:
            ImportError: If ``mermaid-py`` is not installed.
        """
        try:
            import mermaid as md
            from mermaid.graph import Graph
        except ImportError:
            raise ImportError(
                "PNG export requires the mermaid-py package. Install it with: pip install agno[visualize]"
            ) from None

        graph = Graph("workflow", self._mermaid)
        render = md.Mermaid(graph)

        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)

        img_response = render.img_response
        if img_response is None:
            raise RuntimeError("Mermaid rendering returned no PNG data. Check network connectivity to mermaid.ink.")
        resp: Response = img_response
        dest.write_bytes(resp.content)
        return dest.resolve()

    # ------------------------------------------------------------------
    # Show in default viewer
    # ------------------------------------------------------------------

    def show(self) -> None:
        """Open the diagram in the default image viewer.

        Requires ``pip install agno[visualize]`` (mermaid-py + Pillow).
        """
        try:
            import mermaid as md
            from mermaid.graph import Graph
        except ImportError:
            raise ImportError(
                "mermaid-py package is required for image rendering. Install it with: pip install agno[visualize]"
            ) from None

        try:
            from PIL import Image as PILImage
        except ImportError:
            raise ImportError(
                "Pillow package is required for image rendering. Install it with: pip install agno[visualize]"
            ) from None

        from io import BytesIO

        graph = Graph("workflow", self._mermaid)
        render = md.Mermaid(graph)
        img_response = render.img_response
        if img_response is None:
            raise RuntimeError("Mermaid rendering returned no PNG data. Check network connectivity to mermaid.ink.")
        resp: Response = img_response

        image = PILImage.open(BytesIO(resp.content))
        image.show()

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        lines = self._mermaid.count("\n")
        return f"WorkflowVisualization(lines={lines}, workflow={self._workflow_name!r})"

    def __str__(self) -> str:
        return self._mermaid
