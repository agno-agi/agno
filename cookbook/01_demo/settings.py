"""
Settings
========

Shared runtime objects. Keep the model id in one place.
"""

from agno.models.google import Gemini


def gemini_flash() -> Gemini:
    """Gemini 3.5 Flash — every agent in the demo runs on this model."""
    return Gemini(id="gemini-3.5-flash")
