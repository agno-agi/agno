from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AgentKnowledge:
    """V1 compatibility stub for agent knowledge/RAG base class"""
    name: Optional[str] = None
    description: Optional[str] = None
    valid_metadata_filters: Optional[Dict[str, Any]] = None
    extra_data: Dict[str, Any] = field(default_factory=dict)

    def initialize_valid_filters(self) -> None:
        """Initialize valid metadata filters - stub implementation"""
        if self.valid_metadata_filters is None:
            self.valid_metadata_filters = {}

    def search(self, query: str, **kwargs) -> List[Dict[str, Any]]:
        """Search knowledge base - stub implementation"""
        return []

    def add(self, content: str, **kwargs) -> None:
        """Add content to knowledge base - stub implementation"""
        pass

    def update(self, content: str, **kwargs) -> None:
        """Update knowledge base content - stub implementation"""
        pass
