from abc import ABC, abstractmethod
from enum import Enum
from typing import List, Optional

from agno.db.session import Session


class SessionType(str, Enum):
    AGENT = "agent"
    TEAM = "team"
    WORKFLOW = "workflow"


class BaseDb(ABC):
    def __init__(
        self,
        agent_session_table: Optional[str] = None,
        team_session_table: Optional[str] = None,
        workflow_session_table: Optional[str] = None,
        user_memory_table: Optional[str] = None,
        learning_table: Optional[str] = None,
        eval_table: Optional[str] = None,
    ):
        if (
            not agent_session_table
            and not team_session_table
            and not workflow_session_table
            and not user_memory_table
            and not learning_table
            and not eval_table
        ):
            raise ValueError("At least one of the tables must be provided")

        self.agent_session_table_name = agent_session_table
        self.team_session_table_name = team_session_table
        self.workflow_session_table_name = workflow_session_table
        self.user_memory_table_name = user_memory_table
        self.learning_table_name = learning_table
        self.eval_table_name = eval_table

    # --- READ ---

    @abstractmethod
    def get_session(self, session_id: str) -> Optional[Session]:
        raise NotImplementedError

    @abstractmethod
    def get_sessions(self, entity_id: Optional[str] = None) -> List[Session]:
        raise NotImplementedError

    @abstractmethod
    def get_recent_sessions(self, entity_id: Optional[str] = None) -> List[str]:
        raise NotImplementedError

    @abstractmethod
    def get_all_session_ids(self, agent_id: Optional[str] = None) -> List[str]:
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
