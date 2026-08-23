"""Rendering helpers — convert Mermaid source to SVG, PNG, or display.

Uses the mermaid.ink HTTP API directly via ``httpx`` (already a core
dependency of agno).  No extra packages needed for SVG/PNG export.

The server URL defaults to ``https://mermaid.ink`` and can be overridden
per-call via the ``ink_server`` constructor parameter, or globally via
the ``MERMAID_INK_SERVER`` environment variable.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Optional, Union

import httpx

DEFAULT_INK_SERVER = "https://mermaid.ink"


class WorkflowVisualization:
    """Holds a generated Mermaid diagram and provides export methods.

    * ``to_mermaid()`` — always available (pure Python, no extra deps)
    * ``to_svg(path)`` — renders via mermaid.ink (uses ``httpx``, a core dep)
    * ``to_png(path)`` — renders via mermaid.ink (uses ``httpx``, a core dep)
    * ``show()`` — opens in default image viewer (requires ``pip install Pillow``)

    Args:
        mermaid_text: The Mermaid flowchart source.
        workflow_name: Optional label for ``__repr__``.
        ink_server: Base URL of a mermaid-ink server.  Falls back to the
            ``MERMAID_INK_SERVER`` env var, then ``DEFAULT_INK_SERVER``.
    """

    def __init__(
        self,
        mermaid_text: str,
        workflow_name: Optional[str] = None,
        ink_server: Optional[str] = None,
    ) -> None:
        self._mermaid = mermaid_text
        self._workflow_name = workflow_name
        self._ink_server = (
            ink_server
            or os.environ.get("MERMAID_INK_SERVER")
            or DEFAULT_INK_SERVER
        ).rstrip("/")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _encode(self) -> str:
        """Base64url-encode the Mermaid source for the ink API."""
        return base64.urlsafe_b64encode(self._mermaid.encode("utf-8")).decode("ascii")

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
        """Render the diagram to an SVG file via the mermaid-ink API.

        Args:
            path: Destination file path.

        Returns:
            The resolved ``Path`` that was written.
        """
        url = f"{self._ink_server}/svg/{self._encode()}"
        resp = httpx.get(url, timeout=30)
        resp.raise_for_status()

        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(resp.text, encoding="utf-8")
        return dest.resolve()

    # ------------------------------------------------------------------
    # PNG export
    # ------------------------------------------------------------------

    def to_png(self, path: Union[str, Path]) -> Path:
        """Render the diagram to a PNG file via the mermaid-ink API.

        Args:
            path: Destination file path.

        Returns:
            The resolved ``Path`` that was written.
        """
        url = f"{self._ink_server}/img/{self._encode()}"
        resp = httpx.get(url, timeout=30)
        resp.raise_for_status()

        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        return dest.resolve()

    # ------------------------------------------------------------------
    # Show in default viewer
    # ------------------------------------------------------------------

    def show(self) -> None:
        """Open the diagram in the default image viewer.

        Requires ``pip install Pillow``.
        """
        try:
            from PIL import Image as PILImage
        except ImportError:
            raise ImportError(
                "Pillow is required for show(). Install it with: pip install Pillow"
            ) from None

        from io import BytesIO

        url = f"{self._ink_server}/img/{self._encode()}"
        resp = httpx.get(url, timeout=30)
        resp.raise_for_status()

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
