"""V1 session summarizer compatibility stub."""

from abc import ABC, abstractmethod
from typing import Optional

from agno.models.base import Model


class SessionSummarizer(ABC):
    """V1-compatible session summarizer base class."""

    def __init__(self, model: Optional[Model] = None, **kwargs):
        """Initialize summarizer."""
        self.model = model

    @abstractmethod
    def summarize(self, session_content: str, **kwargs) -> str:
        """Summarize session content."""
        pass

    @abstractmethod
    def generate_key_points(self, session_content: str, **kwargs) -> list[str]:
        """Extract key points from session content."""
        pass
