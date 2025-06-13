from abc import ABC, abstractmethod
from enum import Enum
from typing import List, Optional

from agno.storage.session import Session


class SessionType(str, Enum):
    AGENT = "agent"
    TEAM = "team"
    WORKFLOW = "workflow"


class Storage(ABC):
    def __init__(
        self,
        agent_sessions_table: Optional[str] = None,
        team_sessions_table: Optional[str] = None,
        workflow_sessions_table: Optional[str] = None,
        user_memories_table: Optional[str] = None,
        learnings_table: Optional[str] = None,
        evals_table: Optional[str] = None,
    ):
        if (
            not agent_sessions_table
            and not team_sessions_table
            and not workflow_sessions_table
            and not user_memories_table
            and not learnings_table
            and not evals_table
        ):
            raise ValueError("At least one of the tables must be provided")

        self.agent_sessions_table = agent_sessions_table
        self.team_sessions_table = team_sessions_table
        self.workflow_sessions_table = workflow_sessions_table
        self.user_memories_table = user_memories_table
        self.learnings_table = learnings_table
        self.evals_table = evals_table

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
