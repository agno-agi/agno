from abc import ABC, abstractmethod
from typing import List, Literal, Optional

from agno.storage.session import Session


class Storage(ABC):
    def __init__(self, mode: Optional[Literal["agent", "team", "workflow"]] = "agent"):
        self._mode: Literal["agent", "team", "workflow"] = "agent" if mode is None else mode

    @property
    def mode(self) -> Literal["agent", "team", "workflow"]:
        """Get the mode of the storage."""
        return self._mode

    @mode.setter
    def mode(self, value: Optional[Literal["agent", "team", "workflow"]]) -> None:
        """Set the mode of the storage."""
        self._mode = "agent" if value is None else value

    @abstractmethod
    def create(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def read(self, session_id: str, user_id: Optional[str] = None) -> Optional[Session]:
        raise NotImplementedError

    @abstractmethod
    def get_all_session_ids(self, user_id: Optional[str] = None, agent_id: Optional[str] = None) -> List[str]:
        raise NotImplementedError

    @abstractmethod
    def get_all_sessions(self, user_id: Optional[str] = None, entity_id: Optional[str] = None) -> List[Session]:
        raise NotImplementedError

    def get_last_n_sessions(
        self, number_of_sessions: Optional[int] = 3, user_id: Optional[str] = None, entity_id: Optional[str] = None
    ) -> List[Session]:
        """Get the last N sessions, sorted by created_at timestamp in descending order.

        Args:
            n (int): Number of most recent sessions to return
            user_id (Optional[str]): Filter sessions by user ID
            entity_id (Optional[str]): Filter sessions by entity ID (agent_id, team_id, or workflow_id)

        Returns:
            List[Session]: List of the N most recent sessions, sorted by created_at in descending order
        """
        # Get all sessions using the existing method
        sessions = self.get_all_sessions(user_id=user_id, entity_id=entity_id)

        # Sort sessions by created_at in descending order (newest first)
        sorted_sessions = sorted(sessions, key=lambda x: x.created_at if x.created_at else 0, reverse=True)

        # Return only the first N sessions
        return sorted_sessions[:number_of_sessions]

    @abstractmethod
    def upsert(self, session: Session) -> Optional[Session]:
        raise NotImplementedError

    @abstractmethod
    def delete_session(self, session_id: Optional[str] = None):
        raise NotImplementedError

    @abstractmethod
    def drop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def upgrade_schema(self) -> None:
        raise NotImplementedError
