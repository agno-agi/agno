from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional

from sqlalchemy import Table

from agno.memory.db.schema import MemoryRow
from agno.session import Session


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
        knowledge_table: Optional[str] = None,
    ):
        if (
            not agent_session_table
            and not team_session_table
            and not workflow_session_table
            and not user_memory_table
            and not learning_table
            and not eval_table
            and not knowledge_table
        ):
            raise ValueError("At least one of the tables must be provided")

        self.agent_session_table_name = agent_session_table
        self.team_session_table_name = team_session_table
        self.workflow_session_table_name = workflow_session_table
        self.user_memory_table_name = user_memory_table
        self.learning_table_name = learning_table
        self.eval_table_name = eval_table
        self.knowledge_table_name = knowledge_table

    # --- Base ---

    @abstractmethod
    def create_schema(self, db_schema: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def create_table(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_or_create_table(self, table_name: str, table_type: str, db_schema: str) -> Optional[Table]:
        raise NotImplementedError

    @abstractmethod
    def table_exists(self, table_name: str, db_schema: str) -> bool:
        raise NotImplementedError

    # @abstractmethod
    # def upgrade_schema(self) -> None:
    #     raise NotImplementedError

    # --- Sessions Table ---

    @abstractmethod
    def delete_session(self, session_id: Optional[str] = None):
        raise NotImplementedError

    @abstractmethod
    def get_runs_raw(self, session_id: str, session_type: SessionType) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_session_raw(
        self, session_id: str, session_type: SessionType, user_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_session(
        self, session_id: str, session_type: SessionType, user_id: Optional[str] = None
    ) -> Optional[Session]:
        raise NotImplementedError

    @abstractmethod
    def get_sessions_raw(
        self,
        session_type: SessionType,
        user_id: Optional[str] = None,
        component_id: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_sessions(
        self,
        session_type: SessionType,
        user_id: Optional[str] = None,
        component_id: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> List[Session]:
        raise NotImplementedError

    @abstractmethod
    def get_recent_sessions(
        self, session_type: SessionType, component_id: Optional[str] = None, limit: Optional[int] = None
    ) -> List[str]:
        raise NotImplementedError

    @abstractmethod
    def get_all_session_ids(self, session_type: SessionType, entity_id: Optional[str] = None) -> List[str]:
        raise NotImplementedError

    @abstractmethod
    def upsert_session_raw(self, session: Session) -> Optional[Session]:
        raise NotImplementedError

    @abstractmethod
    def upsert_session(self, session: Session) -> Optional[Session]:
        raise NotImplementedError

    # --- User Memory Table ---

    @abstractmethod
    def delete_user_memory(self, memory_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_user_memory_raw(self, memory_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_user_memory(self, memory_id: str) -> Optional[MemoryRow]:
        raise NotImplementedError

    @abstractmethod
    def get_user_memories_raw(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        topics: Optional[List[str]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_user_memories(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        topics: Optional[List[str]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> List[MemoryRow]:
        raise NotImplementedError

    @abstractmethod
    def upsert_user_memory_raw(self, memory: MemoryRow) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def upsert_user_memory(self, memory: MemoryRow) -> Optional[MemoryRow]:
        raise NotImplementedError

    @abstractmethod
    def get_unique_topics(self) -> List[str]:
        raise NotImplementedError

    # --- Knowledge Table ---

    @abstractmethod
    def get_knowledge_document(self, knowledge_id: str):
        raise NotImplementedError

    @abstractmethod
    def get_knowledge_documents(self, knowledge_id: str):
        raise NotImplementedError

    @abstractmethod
    def upsert_knowledge_document(self):
        raise NotImplementedError

    @abstractmethod
    def delete_knowledge_document(self):
        raise NotImplementedError
