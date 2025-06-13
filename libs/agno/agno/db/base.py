from abc import ABC, abstractmethod
from typing import List, Optional

from agno.storage.session import Session


class BaseDb(ABC):
    def __init__(
        self,
        agent_sessions: Optional[str] = None,
        team_sessions: Optional[str] = None,
        workflow_sessions: Optional[str] = None,
        memories: Optional[str] = None,
        learnings: Optional[str] = None,
        evals: Optional[str] = None,
    ):
        if (
            not agent_sessions
            and not team_sessions
            and not workflow_sessions
            and not memories
            and not learnings
            and not evals
        ):
            raise ValueError("At least one of the tables must be provided")

        self.agent_sessions = agent_sessions
        self.team_sessions = team_sessions
        self.workflow_sessions = workflow_sessions
        self.memories = memories
        self.learnings = learnings
        self.evals = evals

    # --- READ ---

    @abstractmethod
    def get_session(self, session_id: str) -> Optional[Session]:
        raise NotImplementedError

    @abstractmethod
    def get_all_session_ids(self, agent_id: Optional[str] = None) -> List[str]:
        raise NotImplementedError

    @abstractmethod
    def get_sessions(self, entity_id: Optional[str] = None) -> List[Session]:
        raise NotImplementedError

    # --- WRITE ---

    @abstractmethod
    def create_table(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete_session(self, session_id: Optional[str] = None):
        raise NotImplementedError

    # @abstractmethod
    # def upsert(self, session: Session) -> Optional[Session]:
    #     raise NotImplementedError

    # --- UTILITIES ---

    # @abstractmethod
    # def create_table(self, table_name: str, schema: str) -> None:
    #     raise NotImplementedError

    # @abstractmethod
    # def validate_table_schema(self, table_name: str, schema: str) -> None:
    #     raise NotImplementedError

    # @abstractmethod
    # def upgrade_schema(self) -> None:
    #     raise NotImplementedError