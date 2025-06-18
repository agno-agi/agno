from abc import ABC, abstractmethod
from enum import Enum
from typing import List, Optional, Union

from agno.eval.schemas import EvalRunRecord
from agno.memory.db.schema import MemoryRow
from agno.run.response import RunResponse
from agno.run.team import TeamRunResponse
from agno.session import AgentSession, Session


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
    def get_runs(self, session_id: str, session_type: SessionType) -> List[Union[RunResponse, TeamRunResponse]]:
        raise NotImplementedError

    @abstractmethod
    def get_session(self, session_id: str, session_type: SessionType) -> Optional[Session]:
        raise NotImplementedError

    @abstractmethod
    def get_sessions(
        self, session_type: SessionType, entity_id: Optional[str] = None, limit: Optional[int] = None
    ) -> List[Session]:
        raise NotImplementedError

    @abstractmethod
    def get_recent_sessions(
        self, session_type: SessionType, entity_id: Optional[str] = None, limit: Optional[int] = None
    ) -> List[str]:
        raise NotImplementedError

    @abstractmethod
    def get_all_session_ids(self, session_type: SessionType, entity_id: Optional[str] = None) -> List[str]:
        raise NotImplementedError

    @abstractmethod
    def get_user_memory(self, memory_id: str) -> Optional[MemoryRow]:
        raise NotImplementedError

    @abstractmethod
    def get_user_memories(self, user_id: Optional[str] = None) -> List[MemoryRow]:
        raise NotImplementedError

    # --- WRITE ---

    @abstractmethod
    def create_eval_run(self, eval_run: EvalRunRecord) -> Optional[EvalRunRecord]:
        raise NotImplementedError

    @abstractmethod
    def create_table(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete_session(self, session_id: Optional[str] = None):
        raise NotImplementedError

    @abstractmethod
    def delete_user_memory(self, memory_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def upsert_agent_session(self, session: AgentSession) -> Optional[AgentSession]:
        raise NotImplementedError

    @abstractmethod
    def upsert_user_memory(self, memory: MemoryRow) -> Optional[MemoryRow]:
        raise NotImplementedError

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
