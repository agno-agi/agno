from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agno.embedder import Embedder


@dataclass
class Document:
    """Dataclass for managing a document"""

    content: str
    id: Optional[str] = None
    name: Optional[str] = None
    meta_data: Dict[str, Any] = field(default_factory=dict)
    embedder: Optional[Embedder] = None
    embedding: Optional[List[float]] = None
    usage: Optional[Dict[str, Any]] = None
    reranking_score: Optional[float] = None

    def embed(self, embedder: Optional[Embedder] = None) -> None:
        """Embed the document using the provided embedder"""

        _embedder = embedder or self.embedder
        if _embedder is None:
            raise ValueError("No embedder provided")

        self.embedding, self.usage = _embedder.get_embedding_and_usage(self.content)

    def to_dict(self) -> Dict[str, Any]:
        """Returns a dictionary representation of the document"""
        fields = {"name", "meta_data", "content"}
        return {
            field: getattr(self, field)
            for field in fields
            if getattr(self, field) is not None or field == "content"  # content is always included
        }

    @classmethod
    def from_dict(cls, document: Dict[str, Any]) -> "Document":
        """Returns a Document object from a dictionary representation"""
        return cls(**document)

    @classmethod
    def from_json(cls, document: str) -> "Document":
        """Returns a Document object from a json string representation"""
        import json

        return cls(**json.loads(document))
