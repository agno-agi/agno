from abc import ABC, abstractmethod
from datetime import date
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import Table

from agno.db.schemas import MemoryRow
from agno.db.schemas.knowledge import KnowledgeRow
from agno.eval.schemas import EvalFilterType, EvalRunRecord, EvalType
from agno.session import Session


class SessionType(str, Enum):
    AGENT = "agent"
    TEAM = "team"
    WORKFLOW = "workflow"


class BaseDb(ABC):
    def __init__(
        self,
        session_table: Optional[str] = None,
        user_memory_table: Optional[str] = None,
        metrics_table: Optional[str] = None,
        eval_table: Optional[str] = None,
        knowledge_table: Optional[str] = None,
    ):
        if (
            not session_table
            and not user_memory_table
            and not metrics_table
            and not eval_table
            and not knowledge_table
        ):
            raise ValueError("At least one of the tables must be provided")

        self.session_table_name = session_table
        self.user_memory_table_name = user_memory_table
        self.metrics_table_name = metrics_table
        self.eval_table_name = eval_table
        self.knowledge_table_name = knowledge_table

    # --- Base ---

    @abstractmethod
    def _create_table(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def _get_table(self, table_type: str) -> Table:
        raise NotImplementedError

    @abstractmethod
    def _get_or_create_table(self, table_name: str, table_type: str, db_schema: str) -> Optional[Table]:
        raise NotImplementedError

    # --- Sessions Table ---

    @abstractmethod
    def delete_session(self, session_id: Optional[str] = None, session_type: SessionType = SessionType.AGENT):
        raise NotImplementedError

    @abstractmethod
    def delete_sessions(self, session_ids: List[str]) -> None:
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
        session_name: Optional[str] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        raise NotImplementedError

    @abstractmethod
    def get_sessions(
        self,
        session_type: SessionType,
        user_id: Optional[str] = None,
        component_id: Optional[str] = None,
        session_name: Optional[str] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> List[Session]:
        raise NotImplementedError

    @abstractmethod
    def rename_session(self, session_id: str, session_type: SessionType, session_name: str) -> Optional[Session]:
        raise NotImplementedError

    @abstractmethod
    def upsert_session(self, session: Session) -> Optional[Session]:
        raise NotImplementedError

    # --- User Memory Table ---

    @abstractmethod
    def delete_user_memory(self, memory_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete_user_memories(self, memory_ids: List[str]) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_all_memory_topics(self) -> List[str]:
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
        search_content: Optional[str] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        raise NotImplementedError

    @abstractmethod
    def get_user_memories(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        topics: Optional[List[str]] = None,
        search_content: Optional[str] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> List[MemoryRow]:
        raise NotImplementedError

    @abstractmethod
    def get_user_memory_stats(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        raise NotImplementedError

    @abstractmethod
    def upsert_user_memory_raw(self, memory: MemoryRow) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def upsert_user_memory(self, memory: MemoryRow) -> Optional[MemoryRow]:
        raise NotImplementedError

    # --- Metrics Table ---

    @abstractmethod
    def calculate_metrics(self) -> Optional[Any]:
        raise NotImplementedError

    @abstractmethod
    def get_metrics_raw(
        self, starting_date: Optional[date] = None, ending_date: Optional[date] = None
    ) -> Tuple[List[Any], Optional[int]]:
        raise NotImplementedError

    # --- Knowledge Table ---

    @abstractmethod
    def get_document_status(self, document_id: str) -> Optional[str]:
        """Get the status of a knowledge document by ID."""
        raise NotImplementedError

    @abstractmethod
    def get_knowledge_document(self, document_id: str) -> Optional[KnowledgeRow]:
        """Get a knowledge document by ID."""
        raise NotImplementedError

    @abstractmethod
    def get_knowledge_documents(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> Tuple[List[KnowledgeRow], int]:
        """Get all knowledge documents from the database."""
        raise NotImplementedError

    @abstractmethod
    def upsert_knowledge_document(self, knowledge_row: KnowledgeRow):
        """Upsert a knowledge document in the database."""
        raise NotImplementedError

    @abstractmethod
    def delete_knowledge_document(self, document_id: str):
        """Delete a knowledge document by ID."""
        raise NotImplementedError

    # --- Eval Table ---

    @abstractmethod
    def create_eval_run(self, eval_run: EvalRunRecord) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def delete_eval_runs(self, eval_run_ids: List[str]) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_eval_run_raw(self, eval_run_id: str, table: Optional[Table] = None) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_eval_run(self, eval_run_id: str, table: Optional[Table] = None) -> Optional[EvalRunRecord]:
        raise NotImplementedError

    @abstractmethod
    def get_eval_runs_raw(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        table: Optional[Table] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        model_id: Optional[str] = None,
        eval_type: Optional[List[EvalType]] = None,
        filter_type: Optional[EvalFilterType] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        raise NotImplementedError

    @abstractmethod
    def get_eval_runs(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        table: Optional[Table] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        model_id: Optional[str] = None,
        eval_type: Optional[List[EvalType]] = None,
    ) -> List[EvalRunRecord]:
        raise NotImplementedError

    @abstractmethod
    def rename_eval_run(self, eval_run_id: str, name: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError
