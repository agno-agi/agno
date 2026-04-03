from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal

from pydantic import BaseModel, Field

# -- Indexing ------------------------------------------------------------------


class IndexedDocument(BaseModel):
    """Metadata for an indexed document."""

    doc_id: str
    doc_name: str
    doc_type: Literal["pdf", "md"]
    source_path: str
    structure_path: str
    indexed_at: datetime


class BatchIndexResponse(BaseModel):
    """Result of a batch-index operation."""

    indexed: List[IndexedDocument]
    failed: List[str]


# -- Retrieval -----------------------------------------------------------------


class RetrievalResult(BaseModel):
    """A single retrieval hit from keyword search."""

    content: str
    doc_id: str = ""
    doc_name: str = ""
    title: str = ""
    node_id: str = ""
    start_index: int = 0
    end_index: int = 0
    score: int = 0
    term_coverage: float = 0.0
    source_path: str = ""
    insufficient_evidence: bool = False


# -- Structure -----------------------------------------------------------------


class StructureResponse(BaseModel):
    """The hierarchical tree JSON of a document."""

    doc_id: str
    doc_name: str
    structure: Any = Field(description="The hierarchical tree JSON.")
