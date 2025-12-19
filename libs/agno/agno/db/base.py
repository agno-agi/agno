from abc import ABC, abstractmethod
from datetime import date, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

if TYPE_CHECKING:
    from agno.tracing.schemas import Span, Trace

from agno.db.schemas import UserMemory
from agno.db.schemas.culture import CulturalKnowledge
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.db.schemas.knowledge import KnowledgeRow
from agno.session import Session


class SessionType(str, Enum):
    AGENT = "agent"
    TEAM = "team"
    WORKFLOW = "workflow"


class BaseDb(ABC):
    """Base abstract class for all our Database implementations."""

    # We assume the database to be up to date with the 2.0.0 release
    default_schema_version = "2.0.0"

    def __init__(
        self,
        session_table: Optional[str] = None,
        culture_table: Optional[str] = None,
        memory_table: Optional[str] = None,
        metrics_table: Optional[str] = None,
        eval_table: Optional[str] = None,
        knowledge_table: Optional[str] = None,
        traces_table: Optional[str] = None,
        spans_table: Optional[str] = None,
        versions_table: Optional[str] = None,
        id: Optional[str] = None,
    ):
        self.id = id or str(uuid4())
        self.session_table_name = session_table or "agno_sessions"
        self.culture_table_name = culture_table or "agno_culture"
        self.memory_table_name = memory_table or "agno_memories"
        self.metrics_table_name = metrics_table or "agno_metrics"
        self.eval_table_name = eval_table or "agno_eval_runs"
        self.knowledge_table_name = knowledge_table or "agno_knowledge"
        self.trace_table_name = traces_table or "agno_traces"
        self.span_table_name = spans_table or "agno_spans"
        self.versions_table_name = versions_table or "agno_schema_versions"

    @abstractmethod
    def table_exists(self, table_name: str) -> bool:
        raise NotImplementedError

    def _create_all_tables(self) -> None:
        """Create all tables for this database."""
        pass

    def close(self) -> None:
        """Close database connections and release resources.

        Override in subclasses to properly dispose of connection pools.
        Should be called during application shutdown.
        """
        pass

    # --- Schema Version ---
    @abstractmethod
    def get_latest_schema_version(self, table_name: str):
        raise NotImplementedError

    @abstractmethod
    def upsert_schema_version(self, table_name: str, version: str):
        """Upsert the schema version into the database."""
        raise NotImplementedError

    # --- Sessions ---
    @abstractmethod
    def delete_session(self, session_id: str) -> bool:
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
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Union[List[Session], Tuple[List[Dict[str, Any]], int]]:
        raise NotImplementedError

    @abstractmethod
    def rename_session(
        self,
        session_id: str,
        session_type: SessionType,
        session_name: str,
        deserialize: Optional[bool] = True,
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        raise NotImplementedError

    @abstractmethod
    def upsert_session(
        self, session: Session, deserialize: Optional[bool] = True
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        raise NotImplementedError

    @abstractmethod
    def upsert_sessions(
        self,
        sessions: List[Session],
        deserialize: Optional[bool] = True,
        preserve_updated_at: bool = False,
    ) -> List[Union[Session, Dict[str, Any]]]:
        """Bulk upsert multiple sessions for improved performance on large datasets."""
        raise NotImplementedError

    # --- Memory ---
    @abstractmethod
    def clear_memories(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete_user_memory(self, memory_id: str, user_id: Optional[str] = None) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete_user_memories(self, memory_ids: List[str], user_id: Optional[str] = None) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_all_memory_topics(self, user_id: Optional[str] = None) -> List[str]:
        raise NotImplementedError

    @abstractmethod
    def get_user_memory(
        self,
        memory_id: str,
        deserialize: Optional[bool] = True,
        user_id: Optional[str] = None,
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        raise NotImplementedError

    @abstractmethod
    def get_user_memories(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
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
        user_id: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        raise NotImplementedError

    @abstractmethod
    def upsert_user_memory(
        self, memory: UserMemory, deserialize: Optional[bool] = True
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        raise NotImplementedError

    @abstractmethod
    def upsert_memories(
        self,
        memories: List[UserMemory],
        deserialize: Optional[bool] = True,
        preserve_updated_at: bool = False,
    ) -> List[Union[UserMemory, Dict[str, Any]]]:
        """Bulk upsert multiple memories for improved performance on large datasets."""
        raise NotImplementedError

    # --- Metrics ---
    @abstractmethod
    def get_metrics(
        self,
        starting_date: Optional[date] = None,
        ending_date: Optional[date] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        raise NotImplementedError

    @abstractmethod
    def calculate_metrics(self) -> Optional[Any]:
        raise NotImplementedError

    # --- Knowledge ---
    @abstractmethod
    def delete_knowledge_content(self, id: str):
        """Delete a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to delete.
        """
        raise NotImplementedError

    @abstractmethod
    def get_knowledge_content(self, id: str) -> Optional[KnowledgeRow]:
        """Get a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to get.

        Returns:
            Optional[KnowledgeRow]: The knowledge row, or None if it doesn't exist.
        """
        raise NotImplementedError

    @abstractmethod
    def get_knowledge_contents(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> Tuple[List[KnowledgeRow], int]:
        """Get all knowledge contents from the database.

        Args:
            limit (Optional[int]): The maximum number of knowledge contents to return.
            page (Optional[int]): The page number.
            sort_by (Optional[str]): The column to sort by.
            sort_order (Optional[str]): The order to sort by.

        Returns:
            Tuple[List[KnowledgeRow], int]: The knowledge contents and total count.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        raise NotImplementedError

    @abstractmethod
    def upsert_knowledge_content(self, knowledge_row: KnowledgeRow):
        """Upsert knowledge content in the database.

        Args:
            knowledge_row (KnowledgeRow): The knowledge row to upsert.

        Returns:
            Optional[KnowledgeRow]: The upserted knowledge row, or None if the operation fails.
        """
        raise NotImplementedError

    # --- Evals ---
    @abstractmethod
    def create_eval_run(self, eval_run: EvalRunRecord) -> Optional[EvalRunRecord]:
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

    # --- Traces ---
    @abstractmethod
    def upsert_trace(self, trace: "Trace") -> None:
        """Create or update a single trace record in the database.

        Args:
            trace: The Trace object to store (one per trace_id).
        """
        raise NotImplementedError

    @abstractmethod
    def get_trace(
        self,
        trace_id: Optional[str] = None,
        run_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ):
        """Get a single trace by trace_id or other filters.

        Args:
            trace_id: The unique trace identifier.
            run_id: Filter by run ID (returns first match).
            session_id: Filter by session ID (returns first match).
            user_id: Filter by user ID (returns first match).
            agent_id: Filter by agent ID (returns first match).

        Returns:
            Optional[Trace]: The trace if found, None otherwise.

        Note:
            If multiple filters are provided, trace_id takes precedence.
            For other filters, the most recent trace is returned.
        """
        raise NotImplementedError

    @abstractmethod
    def get_traces(
        self,
        run_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        status: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: Optional[int] = 20,
        page: Optional[int] = 1,
    ) -> tuple[List, int]:
        """Get traces matching the provided filters with pagination.

        Args:
            run_id: Filter by run ID.
            session_id: Filter by session ID.
            user_id: Filter by user ID.
            agent_id: Filter by agent ID.
            team_id: Filter by team ID.
            workflow_id: Filter by workflow ID.
            status: Filter by status (OK, ERROR).
            start_time: Filter traces starting after this datetime.
            end_time: Filter traces ending before this datetime.
            limit: Maximum number of traces to return per page.
            page: Page number (1-indexed).

        Returns:
            tuple[List[Trace], int]: Tuple of (list of matching traces with datetime fields, total count).
        """
        raise NotImplementedError

    @abstractmethod
    def get_trace_stats(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: Optional[int] = 20,
        page: Optional[int] = 1,
    ) -> tuple[List[Dict[str, Any]], int]:
        """Get trace statistics grouped by session.

        Args:
            user_id: Filter by user ID.
            agent_id: Filter by agent ID.
            team_id: Filter by team ID.
            workflow_id: Filter by workflow ID.
            start_time: Filter sessions with traces created after this datetime.
            end_time: Filter sessions with traces created before this datetime.
            limit: Maximum number of sessions to return per page.
            page: Page number (1-indexed).

        Returns:
            tuple[List[Dict], int]: Tuple of (list of session stats dicts, total count).
                Each dict contains: session_id, user_id, agent_id, team_id, total_traces,
                first_trace_at (datetime), last_trace_at (datetime).
        """
        raise NotImplementedError

    # --- Spans ---
    @abstractmethod
    def create_span(self, span: "Span") -> None:
        """Create a single span in the database.

        Args:
            span: The Span object to store.
        """
        raise NotImplementedError

    @abstractmethod
    def create_spans(self, spans: List) -> None:
        """Create multiple spans in the database as a batch.

        Args:
            spans: List of Span objects to store.
        """
        raise NotImplementedError

    @abstractmethod
    def get_span(self, span_id: str):
        """Get a single span by its span_id.

        Args:
            span_id: The unique span identifier.

        Returns:
            Optional[Span]: The span if found, None otherwise.
        """
        raise NotImplementedError

    @abstractmethod
    def get_spans(
        self,
        trace_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        limit: Optional[int] = 1000,
    ) -> List:
        """Get spans matching the provided filters.

        Args:
            trace_id: Filter by trace ID.
            parent_span_id: Filter by parent span ID.
            limit: Maximum number of spans to return.

        Returns:
            List[Span]: List of matching spans.
        """
        raise NotImplementedError

    # --- Cultural Knowledge ---
    @abstractmethod
    def clear_cultural_knowledge(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete_cultural_knowledge(self, id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_cultural_knowledge(self, id: str) -> Optional[CulturalKnowledge]:
        raise NotImplementedError

    @abstractmethod
    def get_all_cultural_knowledge(
        self,
        name: Optional[str] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> Optional[List[CulturalKnowledge]]:
        raise NotImplementedError

    @abstractmethod
    def upsert_cultural_knowledge(self, cultural_knowledge: CulturalKnowledge) -> Optional[CulturalKnowledge]:
        raise NotImplementedError


class AsyncBaseDb(ABC):
    """Base abstract class for all our async database implementations."""

    def __init__(
        self,
        id: Optional[str] = None,
        session_table: Optional[str] = None,
        memory_table: Optional[str] = None,
        metrics_table: Optional[str] = None,
        eval_table: Optional[str] = None,
        knowledge_table: Optional[str] = None,
        traces_table: Optional[str] = None,
        spans_table: Optional[str] = None,
        culture_table: Optional[str] = None,
        versions_table: Optional[str] = None,
    ):
        self.id = id or str(uuid4())
        self.session_table_name = session_table or "agno_sessions"
        self.memory_table_name = memory_table or "agno_memories"
        self.metrics_table_name = metrics_table or "agno_metrics"
        self.eval_table_name = eval_table or "agno_eval_runs"
        self.knowledge_table_name = knowledge_table or "agno_knowledge"
        self.trace_table_name = traces_table or "agno_traces"
        self.span_table_name = spans_table or "agno_spans"
        self.culture_table_name = culture_table or "agno_culture"
        self.versions_table_name = versions_table or "agno_schema_versions"

    async def close(self) -> None:
        """Close database connections and release resources.

        Override in subclasses to properly dispose of connection pools.
        Should be called during application shutdown.
        """
        pass

    @abstractmethod
    async def table_exists(self, table_name: str) -> bool:
        """Check if a table with the given name exists in this database.

        Default implementation returns True if the table name is configured.
        Subclasses should override this to perform actual existence checks.

        Args:
            table_name: Name of the table to check

        Returns:
            bool: True if the table exists, False otherwise
        """
        raise NotImplementedError

    @abstractmethod
    async def get_latest_schema_version(self, table_name: str) -> str:
        raise NotImplementedError

    @abstractmethod
    async def upsert_schema_version(self, table_name: str, version: str):
        """Upsert the schema version into the database."""
        raise NotImplementedError

    # --- Sessions ---
    @abstractmethod
    async def delete_session(self, session_id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def delete_sessions(self, session_ids: List[str]) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_session(
        self,
        session_id: str,
        session_type: SessionType,
        user_id: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        raise NotImplementedError

    @abstractmethod
    async def get_sessions(
        self,
        session_type: Optional[SessionType] = None,
        user_id: Optional[str] = None,
        component_id: Optional[str] = None,
        session_name: Optional[str] = None,
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Union[List[Session], Tuple[List[Dict[str, Any]], int]]:
        raise NotImplementedError

    @abstractmethod
    async def rename_session(
        self,
        session_id: str,
        session_type: SessionType,
        session_name: str,
        deserialize: Optional[bool] = True,
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        raise NotImplementedError

    @abstractmethod
    async def upsert_session(
        self, session: Session, deserialize: Optional[bool] = True
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        raise NotImplementedError

    # --- Memory ---
    @abstractmethod
    async def clear_memories(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def delete_user_memory(self, memory_id: str, user_id: Optional[str] = None) -> None:
        raise NotImplementedError

    @abstractmethod
    async def delete_user_memories(self, memory_ids: List[str], user_id: Optional[str] = None) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_all_memory_topics(self, user_id: Optional[str] = None) -> List[str]:
        raise NotImplementedError

    @abstractmethod
    async def get_user_memory(
        self,
        memory_id: str,
        deserialize: Optional[bool] = True,
        user_id: Optional[str] = None,
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        raise NotImplementedError

    @abstractmethod
    async def get_user_memories(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
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
    async def get_user_memory_stats(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        user_id: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        raise NotImplementedError

    @abstractmethod
    async def upsert_user_memory(
        self, memory: UserMemory, deserialize: Optional[bool] = True
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        raise NotImplementedError

    # --- Metrics ---
    @abstractmethod
    async def get_metrics(
        self, starting_date: Optional[date] = None, ending_date: Optional[date] = None
    ) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        raise NotImplementedError

    @abstractmethod
    async def calculate_metrics(self) -> Optional[Any]:
        raise NotImplementedError

    # --- Knowledge ---
    @abstractmethod
    async def delete_knowledge_content(self, id: str):
        """Delete a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to delete.
        """
        raise NotImplementedError

    @abstractmethod
    async def get_knowledge_content(self, id: str) -> Optional[KnowledgeRow]:
        """Get a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to get.

        Returns:
            Optional[KnowledgeRow]: The knowledge row, or None if it doesn't exist.
        """
        raise NotImplementedError

    @abstractmethod
    async def get_knowledge_contents(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> Tuple[List[KnowledgeRow], int]:
        """Get all knowledge contents from the database.

        Args:
            limit (Optional[int]): The maximum number of knowledge contents to return.
            page (Optional[int]): The page number.
            sort_by (Optional[str]): The column to sort by.
            sort_order (Optional[str]): The order to sort by.

        Returns:
            Tuple[List[KnowledgeRow], int]: The knowledge contents and total count.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        raise NotImplementedError

    @abstractmethod
    async def upsert_knowledge_content(self, knowledge_row: KnowledgeRow):
        """Upsert knowledge content in the database.

        Args:
            knowledge_row (KnowledgeRow): The knowledge row to upsert.

        Returns:
            Optional[KnowledgeRow]: The upserted knowledge row, or None if the operation fails.
        """
        raise NotImplementedError

    # --- Evals ---
    @abstractmethod
    async def create_eval_run(self, eval_run: EvalRunRecord) -> Optional[EvalRunRecord]:
        raise NotImplementedError

    @abstractmethod
    async def delete_eval_runs(self, eval_run_ids: List[str]) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_eval_run(
        self, eval_run_id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        raise NotImplementedError

    @abstractmethod
    async def get_eval_runs(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
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
    async def rename_eval_run(
        self, eval_run_id: str, name: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        raise NotImplementedError

    # --- Traces ---
    @abstractmethod
    async def upsert_trace(self, trace) -> None:
        """Create or update a single trace record in the database.

        Args:
            trace: The Trace object to update (one per trace_id).
        """
        raise NotImplementedError

    @abstractmethod
    async def get_trace(
        self,
        trace_id: Optional[str] = None,
        run_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ):
        """Get a single trace by trace_id or other filters.

        Args:
            trace_id: The unique trace identifier.
            run_id: Filter by run ID (returns first match).
            session_id: Filter by session ID (returns first match).
            user_id: Filter by user ID (returns first match).
            agent_id: Filter by agent ID (returns first match).

        Returns:
            Optional[Trace]: The trace if found, None otherwise.

        Note:
            If multiple filters are provided, trace_id takes precedence.
            For other filters, the most recent trace is returned.
        """
        raise NotImplementedError

    @abstractmethod
    async def get_traces(
        self,
        run_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        status: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: Optional[int] = 20,
        page: Optional[int] = 1,
    ) -> tuple[List, int]:
        """Get traces matching the provided filters with pagination.

        Args:
            run_id: Filter by run ID.
            session_id: Filter by session ID.
            user_id: Filter by user ID.
            agent_id: Filter by agent ID.
            team_id: Filter by team ID.
            workflow_id: Filter by workflow ID.
            status: Filter by status (OK, ERROR).
            start_time: Filter traces starting after this datetime.
            end_time: Filter traces ending before this datetime.
            limit: Maximum number of traces to return per page.
            page: Page number (1-indexed).

        Returns:
            tuple[List[Trace], int]: Tuple of (list of matching traces with datetime fields, total count).
        """
        raise NotImplementedError

    @abstractmethod
    async def get_trace_stats(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: Optional[int] = 20,
        page: Optional[int] = 1,
    ) -> tuple[List[Dict[str, Any]], int]:
        """Get trace statistics grouped by session.

        Args:
            user_id: Filter by user ID.
            agent_id: Filter by agent ID.
            team_id: Filter by team ID.
            workflow_id: Filter by workflow ID.
            start_time: Filter sessions with traces created after this datetime.
            end_time: Filter sessions with traces created before this datetime.
            limit: Maximum number of sessions to return per page.
            page: Page number (1-indexed).

        Returns:
            tuple[List[Dict], int]: Tuple of (list of session stats dicts, total count).
                Each dict contains: session_id, user_id, agent_id, team_id, total_traces,
                first_trace_at (datetime), last_trace_at (datetime).
        """
        raise NotImplementedError

    # --- Spans ---
    @abstractmethod
    async def create_span(self, span) -> None:
        """Create a single span in the database.

        Args:
            span: The Span object to store.
        """
        raise NotImplementedError

    @abstractmethod
    async def create_spans(self, spans: List) -> None:
        """Create multiple spans in the database as a batch.

        Args:
            spans: List of Span objects to store.
        """
        raise NotImplementedError

    @abstractmethod
    async def get_span(self, span_id: str):
        """Get a single span by its span_id.

        Args:
            span_id: The unique span identifier.

        Returns:
            Optional[Span]: The span if found, None otherwise.
        """
        raise NotImplementedError

    @abstractmethod
    async def get_spans(
        self,
        trace_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        limit: Optional[int] = 1000,
    ) -> List:
        """Get spans matching the provided filters.

        Args:
            trace_id: Filter by trace ID.
            parent_span_id: Filter by parent span ID.
            limit: Maximum number of spans to return.

        Returns:
            List[Span]: List of matching spans.
        """
        raise NotImplementedError

    # --- Cultural Notions ---
    @abstractmethod
    async def clear_cultural_knowledge(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def delete_cultural_knowledge(self, id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_cultural_knowledge(
        self, id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[CulturalKnowledge, Dict[str, Any]]]:
        raise NotImplementedError

    @abstractmethod
    async def get_all_cultural_knowledge(
        self,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        name: Optional[str] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Union[List[CulturalKnowledge], Tuple[List[Dict[str, Any]], int]]:
        raise NotImplementedError

    @abstractmethod
    async def upsert_cultural_knowledge(
        self, cultural_knowledge: CulturalKnowledge, deserialize: Optional[bool] = True
    ) -> Optional[Union[CulturalKnowledge, Dict[str, Any]]]:
        raise NotImplementedError
