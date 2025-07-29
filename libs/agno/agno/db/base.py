from abc import ABC, abstractmethod
from datetime import date
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

from agno.db.schemas import UserMemory
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.db.schemas.knowledge import KnowledgeRow
from agno.session import Session


class SessionType(str, Enum):
    AGENT = "agent"
    TEAM = "team"
    WORKFLOW = "workflow"


class BaseDb(ABC):
    def __init__(
        self,
        session_table: Optional[str] = None,
        memory_table: Optional[str] = None,
        metrics_table: Optional[str] = None,
        eval_table: Optional[str] = None,
        knowledge_table: Optional[str] = None,
    ):
        self.session_table_name = session_table or "agno_sessions"
        self.memory_table_name = memory_table or "agno_memories"
        self.metrics_table_name = metrics_table or "agno_metrics"
        self.eval_table_name = eval_table or "agno_eval_runs"
        self.knowledge_table_name = knowledge_table or "agno_knowledge"

    # --- Sessions ---
    @abstractmethod
    def delete_session(self, session_id: Optional[str] = None, session_type: SessionType = SessionType.AGENT) -> bool:
        raise NotImplementedError

    @abstractmethod
    def delete_sessions(self, session_ids: List[str]) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_session(
        self,
        session_id: str,
        session_type: SessionType,
        user_id: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Optional[Union[Session, Dict[str, Any]]]:
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
        deserialize: Optional[bool] = True,
    ) -> Union[List[Session], Tuple[List[Dict[str, Any]], int]]:
        raise NotImplementedError

    @abstractmethod
    def rename_session(
        self, session_id: str, session_type: SessionType, session_name: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        raise NotImplementedError

    @abstractmethod
    def upsert_session(
        self, session: Session, deserialize: Optional[bool] = True
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        raise NotImplementedError

    # --- Memory ---

    @abstractmethod
    def clear_memories(self) -> None:
        raise NotImplementedError

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
    def get_user_memory(
        self, memory_id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
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
        deserialize: Optional[bool] = True,
    ) -> Union[List[UserMemory], Tuple[List[Dict[str, Any]], int]]:
        raise NotImplementedError

    @abstractmethod
    def get_user_memory_stats(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        raise NotImplementedError

    @abstractmethod
    def upsert_user_memory(
        self, memory: UserMemory, deserialize: Optional[bool] = True
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        raise NotImplementedError

    @abstractmethod
    def clear_memories(self) -> None:
        raise NotImplementedError

    # --- Metrics ---
    @abstractmethod
    def get_metrics(
        self, starting_date: Optional[date] = None, ending_date: Optional[date] = None
    ) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        raise NotImplementedError

    @abstractmethod
    def calculate_metrics(self) -> Optional[Any]:
        raise NotImplementedError

    # --- Knowledge ---
    @abstractmethod
    def get_knowledge_content(self, id: str) -> Optional[KnowledgeRow]:
        """Get knowledge content by ID."""
        raise NotImplementedError

    @abstractmethod
    def get_knowledge_contents(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> Tuple[List[KnowledgeRow], int]:
        """Get all knowledge content from the database."""
        raise NotImplementedError

    @abstractmethod
    def upsert_knowledge_content(self, knowledge_row: KnowledgeRow):
        """Upsert knowledge content in the database."""
        raise NotImplementedError

    @abstractmethod
    def delete_knowledge_content(self, id: str):
        """Delete knowledge content by ID."""
        raise NotImplementedError

    # --- Evals ---
    @abstractmethod
    def create_eval_run(self, eval_run: EvalRunRecord) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def delete_eval_runs(self, eval_run_ids: List[str]) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_eval_run(
        self, eval_run_id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        raise NotImplementedError

    @abstractmethod
    def get_eval_runs(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        table: Optional[Any] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        model_id: Optional[str] = None,
        filter_type: Optional[EvalFilterType] = None,
        eval_type: Optional[List[EvalType]] = None,
        deserialize: Optional[bool] = True,
    ) -> Union[List[EvalRunRecord], Tuple[List[Dict[str, Any]], int]]:
        raise NotImplementedError

    @abstractmethod
    def rename_eval_run(
        self, eval_run_id: str, name: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        raise NotImplementedError
