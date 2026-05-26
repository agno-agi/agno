"""V1 session summarizer compatibility stub.

V1 had: agno.memory.v2.summarizer.SessionSummarizer
V2 uses: agno.memory.strategies.summarize.SummarizeStrategy

This stub provides a V1-compatible interface for SessionSummarizer.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from agno.models.base import Model


class SessionSummarizer(ABC):
    """V1-compatible session summarizer base class.

    This is a stub providing the V1 interface that agno_custom expects.
    In V2, summarization is handled through SummarizeStrategy.
    """

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
