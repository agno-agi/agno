"""Schemas for external knowledge providers."""

from dataclasses import dataclass, field
from typing import Optional

from agno.knowledge.content import ContentStatus


@dataclass
class ProcessingResult:
    """Result from an external provider ingestion or status check.

    Attributes:
        processing_id: The ID used to poll for status (e.g. LightRAG track_id).
        external_id: The final, resolved external document ID (available once processing completes).
        status: Current processing status.
        status_message: Optional human-readable message about the status.
    """

    processing_id: str
    external_id: Optional[str] = None
    status: ContentStatus = field(default=ContentStatus.PROCESSING)
    status_message: Optional[str] = None
