from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class QueueItem:
    """Represents a queued workflow run"""

    run_id: str
    workflow_id: str
    query: str
    sequence_name: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    status: str = "queued"
    created_at: str = None
    updated_at: Optional[str] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "query": self.query,
            "sequence_name": self.sequence_name,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QueueItem":
        """Create from dictionary"""
        return cls(
            run_id=data["run_id"],
            workflow_id=data["workflow_id"],
            query=data["query"],
            sequence_name=data["sequence_name"],
            user_id=data.get("user_id"),
            session_id=data.get("session_id"),
            status=data.get("status", "queued"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


class Queue(ABC):
    """Abstract base class for workflow queues"""

    @abstractmethod
    def submit(
        self,
        workflow_id: str,
        query: str,
        sequence_name: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> str:
        """Submit a workflow run to the queue

        Returns:
            run_id: Unique identifier for the queued run
        """
        pass

    @abstractmethod
    def get_next_queued(self, workflow_id: str) -> Optional[QueueItem]:
        """Get the next queued item for a specific workflow

        Args:
            workflow_id: The workflow ID to check for

        Returns:
            QueueItem if found, None otherwise
        """
        pass

    @abstractmethod
    def update_status(self, run_id: str, status: str) -> bool:
        """Update the status of a queued run

        Args:
            run_id: The run ID to update
            status: New status (queued, running, completed, failed)

        Returns:
            True if updated successfully, False otherwise
        """
        pass

    @abstractmethod
    def get_all_queued(self) -> List[QueueItem]:
        """Get all queued items"""
        pass

    @abstractmethod
    def get_by_status(self, status: str) -> List[QueueItem]:
        """Get all items with a specific status"""
        pass

    @abstractmethod
    def clear_completed(self) -> int:
        """Remove completed items from queue

        Returns:
            Number of items removed
        """
        pass
