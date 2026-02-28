from abc import ABC, abstractmethod
from datetime import date, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple, Union
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


class ComponentType(str, Enum):
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
        components_table: Optional[str] = None,
        component_configs_table: Optional[str] = None,
        component_links_table: Optional[str] = None,
        learnings_table: Optional[str] = None,
        schedules_table: Optional[str] = None,
        schedule_runs_table: Optional[str] = None,
        approvals_table: Optional[str] = None,
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
        self.components_table_name = components_table or "agno_components"
        self.component_configs_table_name = component_configs_table or "agno_component_configs"
        self.component_links_table_name = component_links_table or "agno_component_links"
        self.learnings_table_name = learnings_table or "agno_learnings"
        self.schedules_table_name = schedules_table or "agno_schedules"
        self.schedule_runs_table_name = schedule_runs_table or "agno_schedule_runs"
        self.approvals_table_name = approvals_table or "agno_approvals"

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize common DB fields (table names + id). Subclasses may extend this.
        """
        return {
            "id": self.id,
            "session_table": self.session_table_name,
            "culture_table": self.culture_table_name,
            "memory_table": self.memory_table_name,
            "metrics_table": self.metrics_table_name,
            "eval_table": self.eval_table_name,
            "knowledge_table": self.knowledge_table_name,
            "traces_table": self.trace_table_name,
            "spans_table": self.span_table_name,
            "versions_table": self.versions_table_name,
            "components_table": self.components_table_name,
            "component_configs_table": self.component_configs_table_name,
            "component_links_table": self.component_links_table_name,
            "learnings_table": self.learnings_table_name,
            "schedules_table": self.schedules_table_name,
            "schedule_runs_table": self.schedule_runs_table_name,
            "approvals_table": self.approvals_table_name,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseDb":
        """
        Reconstruct using only fields defined in BaseDb. Subclasses should override this.
        """
        return cls(
            session_table=data.get("session_table"),
            culture_table=data.get("culture_table"),
            memory_table=data.get("memory_table"),
            metrics_table=data.get("metrics_table"),
            eval_table=data.get("eval_table"),
            knowledge_table=data.get("knowledge_table"),
            traces_table=data.get("traces_table"),
            spans_table=data.get("spans_table"),
            versions_table=data.get("versions_table"),
            components_table=data.get("components_table"),
            component_configs_table=data.get("component_configs_table"),
            component_links_table=data.get("component_links_table"),
            learnings_table=data.get("learnings_table"),
            schedules_table=data.get("schedules_table"),
            schedule_runs_table=data.get("schedule_runs_table"),
            approvals_table=data.get("approvals_table"),
            id=data.get("id"),
        )

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
    def delete_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        raise NotImplementedError

    @abstractmethod
    def delete_sessions(self, session_ids: List[str], user_id: Optional[str] = None) -> None:
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
        user_id: Optional[str] = None,
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
        linked_to: Optional[str] = None,
    ) -> Tuple[List[KnowledgeRow], int]:
        """Get all knowledge contents from the database.

        Args:
            limit (Optional[int]): The maximum number of knowledge contents to return.
            page (Optional[int]): The page number.
            sort_by (Optional[str]): The column to sort by.
            sort_order (Optional[str]): The order to sort by.
            linked_to (Optional[str]): Filter by linked_to value (knowledge instance name).

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

    # --- Components (Optional) ---
    # These methods are optional. Override in subclasses to enable component persistence.
    def get_component(
        self,
        component_id: str,
        component_type: Optional[ComponentType] = None,
    ) -> Optional[Dict[str, Any]]:
        """Get a component by ID.

        Args:
            component_id: The component ID.
            component_type: Optional filter by type (agent|team|workflow).

        Returns:
            Component dictionary or None if not found.
        """
        raise NotImplementedError

    def upsert_component(
        self,
        component_id: str,
        component_type: Optional[ComponentType] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        current_version: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create or update a component.

        Args:
            component_id: Unique identifier.
            component_type: Type (agent|team|workflow). Required for create, optional for update.
            name: Display name.
            description: Optional description.
            current_version: Optional current version.
            metadata: Optional metadata dict.

        Returns:
            Created/updated component dictionary.

        Raises:
            ValueError: If creating and component_type is not provided.
        """
        raise NotImplementedError

    def delete_component(
        self,
        component_id: str,
        hard_delete: bool = False,
    ) -> bool:
        """Delete a component and all its configs/links.

        Args:
            component_id: The component ID.
            hard_delete: If True, permanently delete. Otherwise soft-delete.

        Returns:
            True if deleted, False if not found or already deleted.
        """
        raise NotImplementedError

    def list_components(
        self,
        component_type: Optional[ComponentType] = None,
        include_deleted: bool = False,
        limit: int = 20,
        offset: int = 0,
        exclude_component_ids: Optional[Set[str]] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """List components with pagination.

        Args:
            component_type: Filter by type (agent|team|workflow).
            include_deleted: Include soft-deleted components.
            limit: Maximum number of items to return.
            offset: Number of items to skip.
            exclude_component_ids: Component IDs to exclude from results.

        Returns:
            Tuple of (list of component dicts, total count).
        """
        raise NotImplementedError

    def create_component_with_config(
        self,
        component_id: str,
        component_type: ComponentType,
        name: Optional[str],
        config: Dict[str, Any],
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        label: Optional[str] = None,
        stage: str = "draft",
        notes: Optional[str] = None,
        links: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Create a component with its initial config atomically.

        Args:
            component_id: Unique identifier.
            component_type: Type (agent|team|workflow).
            name: Display name.
            config: The config data.
            description: Optional description.
            metadata: Optional metadata dict.
            label: Optional config label.
            stage: "draft" or "published".
            notes: Optional notes.
            links: Optional list of links. Each must have child_version set.

        Returns:
            Tuple of (component dict, config dict).

        Raises:
            ValueError: If component already exists, invalid stage, or link missing child_version.
        """
        raise NotImplementedError

    # --- Component Configs (Optional) ---
    def get_config(
        self,
        component_id: str,
        version: Optional[int] = None,
        label: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Get a config by component ID and version or label.

        Args:
            component_id: The component ID.
            version: Specific version number. If None, uses current.
            label: Config label to lookup. Ignored if version is provided.

        Returns:
            Config dictionary or None if not found.
        """
        raise NotImplementedError

    def upsert_config(
        self,
        component_id: str,
        config: Optional[Dict[str, Any]] = None,
        version: Optional[int] = None,
        label: Optional[str] = None,
        stage: Optional[str] = None,
        notes: Optional[str] = None,
        links: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Create or update a config version for a component.

        Rules:
            - Draft configs can be edited freely
            - Published configs are immutable
            - Publishing a config automatically sets it as current_version

        Args:
            component_id: The component ID.
            config: The config data. Required for create, optional for update.
            version: If None, creates new version. If provided, updates that version.
            label: Optional human-readable label.
            stage: "draft" or "published". Defaults to "draft" for new configs.
            notes: Optional notes.
            links: Optional list of links. Each link must have child_version set.

        Returns:
            Created/updated config dictionary.

        Raises:
            ValueError: If component doesn't exist, version not found, label conflict,
                        or attempting to update a published config.
        """
        raise NotImplementedError

    def delete_config(
        self,
        component_id: str,
        version: int,
    ) -> bool:
        """Delete a specific config version.

        Only draft configs can be deleted. Published configs are immutable.
        Cannot delete the current version.

        Args:
            component_id: The component ID.
            version: The version to delete.

        Returns:
            True if deleted, False if not found.

        Raises:
            ValueError: If attempting to delete a published or current config.
        """
        raise NotImplementedError

    def list_configs(
        self,
        component_id: str,
        include_config: bool = False,
    ) -> List[Dict[str, Any]]:
        """List all config versions for a component.

        Args:
            component_id: The component ID.
            include_config: If True, include full config blob. Otherwise just metadata.

        Returns:
            List of config dictionaries, newest first.
            Returns empty list if component not found or deleted.
        """
        raise NotImplementedError

    def set_current_version(
        self,
        component_id: str,
        version: int,
    ) -> bool:
        """Set a specific published version as current.

        Only published configs can be set as current. This is used for
        rollback scenarios where you want to switch to a previous
        published version.

        Args:
            component_id: The component ID.
            version: The version to set as current (must be published).

        Returns:
            True if successful, False if component or version not found.

        Raises:
            ValueError: If attempting to set a draft config as current.
        """
        raise NotImplementedError

    # --- Component Links (Optional) ---
    def get_links(
        self,
        component_id: str,
        version: int,
        link_kind: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get links for a config version.

        Args:
            component_id: The component ID.
            version: The config version.
            link_kind: Optional filter by link kind (member|step).

        Returns:
            List of link dictionaries, ordered by position.
        """
        raise NotImplementedError

    def get_dependents(
        self,
        component_id: str,
        version: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Find all components that reference this component.

        Args:
            component_id: The component ID to find dependents of.
            version: Optional specific version. If None, finds links to any version.

        Returns:
            List of link dictionaries showing what depends on this component.
        """
        raise NotImplementedError

    def load_component_graph(
        self,
        component_id: str,
        version: Optional[int] = None,
        label: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Load a component with its full resolved graph.

        Handles cycles by returning a stub with cycle_detected=True.

        Args:
            component_id: The component ID.
            version: Specific version or None for current.
            label: Optional label of the component.

        Returns:
            Dictionary with component, config, children, and resolved_versions.
            Returns None if component not found.
        """
        raise NotImplementedError

    # --- Learnings ---
    @abstractmethod
    def get_learning(
        self,
        learning_type: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve a learning record.

        Args:
            learning_type: Type of learning ('user_profile', 'session_context', etc.)
            user_id: Filter by user ID.
            agent_id: Filter by agent ID.
            team_id: Filter by team ID.
            session_id: Filter by session ID.
            namespace: Filter by namespace ('user', 'global', or custom).
            entity_id: Filter by entity ID (for entity-specific learnings).
            entity_type: Filter by entity type ('person', 'company', etc.).

        Returns:
            Dict with 'content' key containing the learning data, or None.
        """
        raise NotImplementedError

    @abstractmethod
    def upsert_learning(
        self,
        id: str,
        learning_type: str,
        content: Dict[str, Any],
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Insert or update a learning record.

        Args:
            id: Unique identifier for the learning.
            learning_type: Type of learning ('user_profile', 'session_context', etc.)
            content: The learning content as a dict.
            user_id: Associated user ID.
            agent_id: Associated agent ID.
            team_id: Associated team ID.
            session_id: Associated session ID.
            namespace: Namespace for scoping ('user', 'global', or custom).
            entity_id: Associated entity ID (for entity-specific learnings).
            entity_type: Entity type ('person', 'company', etc.).
            metadata: Optional metadata.
        """
        raise NotImplementedError

    @abstractmethod
    def delete_learning(self, id: str) -> bool:
        """Delete a learning record.

        Args:
            id: The learning ID to delete.

        Returns:
            True if deleted, False otherwise.
        """
        raise NotImplementedError

    @abstractmethod
    def get_learnings(
        self,
        learning_type: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Get multiple learning records.

        Args:
            learning_type: Filter by learning type.
            user_id: Filter by user ID.
            agent_id: Filter by agent ID.
            team_id: Filter by team ID.
            session_id: Filter by session ID.
            namespace: Filter by namespace ('user', 'global', or custom).
            entity_id: Filter by entity ID (for entity-specific learnings).
            entity_type: Filter by entity type ('person', 'company', etc.).
            limit: Maximum number of records to return.

        Returns:
            List of learning records.
        """
        raise NotImplementedError

    # --- Schedules (Optional) ---
    # These methods are optional. Override in subclasses to enable scheduler persistence.

    def get_schedule(self, schedule_id: str) -> Optional[Dict[str, Any]]:
        """Get a schedule by ID."""
        raise NotImplementedError

    def get_schedule_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a schedule by name."""
        raise NotImplementedError

    def get_schedules(
        self,
        enabled: Optional[bool] = None,
        limit: int = 100,
        page: int = 1,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """List schedules with optional filtering.

        Returns:
            Tuple of (schedules, total_count)
        """
        raise NotImplementedError

    def create_schedule(self, schedule_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new schedule."""
        raise NotImplementedError

    def update_schedule(self, schedule_id: str, **kwargs: Any) -> Optional[Dict[str, Any]]:
        """Update a schedule by ID."""
        raise NotImplementedError

    def delete_schedule(self, schedule_id: str) -> bool:
        """Delete a schedule and its associated runs."""
        raise NotImplementedError

    def claim_due_schedule(self, worker_id: str, lock_grace_seconds: int = 300) -> Optional[Dict[str, Any]]:
        """Atomically claim a due schedule for execution."""
        raise NotImplementedError

    def release_schedule(self, schedule_id: str, next_run_at: Optional[int] = None) -> bool:
        """Release a claimed schedule and optionally update next_run_at."""
        raise NotImplementedError

    # --- Schedule Runs (Optional) ---

    def create_schedule_run(self, run_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a schedule run record."""
        raise NotImplementedError

    def update_schedule_run(self, schedule_run_id: str, **kwargs: Any) -> Optional[Dict[str, Any]]:
        """Update a schedule run record."""
        raise NotImplementedError

    def get_schedule_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Get a schedule run by ID."""
        raise NotImplementedError

    def get_schedule_runs(
        self,
        schedule_id: str,
        limit: int = 20,
        page: int = 1,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """List runs for a schedule.

        Returns:
            Tuple of (runs, total_count)
        """
        raise NotImplementedError

    # --- Approvals (Optional) ---
    # These methods are optional. Override in subclasses to enable approval persistence.

    def create_approval(self, approval_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create an approval record."""
        raise NotImplementedError

    def get_approval(self, approval_id: str) -> Optional[Dict[str, Any]]:
        """Get an approval by ID."""
        raise NotImplementedError

    def get_approvals(
        self,
        status: Optional[str] = None,
        source_type: Optional[str] = None,
        approval_type: Optional[str] = None,
        pause_type: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        user_id: Optional[str] = None,
        schedule_id: Optional[str] = None,
        run_id: Optional[str] = None,
        limit: int = 100,
        page: int = 1,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """List approvals with optional filtering. Returns (items, total_count)."""
        raise NotImplementedError

    def update_approval(
        self, approval_id: str, expected_status: Optional[str] = None, **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        """Update an approval. If expected_status is set, only updates if current status matches (atomic guard)."""
        raise NotImplementedError

    def delete_approval(self, approval_id: str) -> bool:
        """Delete an approval by ID."""
        raise NotImplementedError

    def get_pending_approval_count(self, user_id: Optional[str] = None) -> int:
        """Get count of pending approvals."""
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
        learnings_table: Optional[str] = None,
        schedules_table: Optional[str] = None,
        schedule_runs_table: Optional[str] = None,
        approvals_table: Optional[str] = None,
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
        self.learnings_table_name = learnings_table or "agno_learnings"
        self.schedules_table_name = schedules_table or "agno_schedules"
        self.schedule_runs_table_name = schedule_runs_table or "agno_schedule_runs"
        self.approvals_table_name = approvals_table or "agno_approvals"

    async def _create_all_tables(self) -> None:
        """Create all tables for this database. Override in subclasses."""
        pass

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
    async def delete_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def delete_sessions(self, session_ids: List[str], user_id: Optional[str] = None) -> None:
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
        user_id: Optional[str] = None,
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
        linked_to: Optional[str] = None,
    ) -> Tuple[List[KnowledgeRow], int]:
        """Get all knowledge contents from the database.

        Args:
            limit (Optional[int]): The maximum number of knowledge contents to return.
            page (Optional[int]): The page number.
            sort_by (Optional[str]): The column to sort by.
            sort_order (Optional[str]): The order to sort by.
            linked_to (Optional[str]): Filter by linked_to value (knowledge instance name).

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

    # --- Learnings ---
    @abstractmethod
    async def get_learning(
        self,
        learning_type: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Async retrieve a learning record.

        Args:
            learning_type: Type of learning ('user_profile', 'session_context', etc.)
            user_id: Filter by user ID.
            agent_id: Filter by agent ID.
            team_id: Filter by team ID.
            session_id: Filter by session ID.
            namespace: Filter by namespace ('user', 'global', or custom).
            entity_id: Filter by entity ID (for entity-specific learnings).
            entity_type: Filter by entity type ('person', 'company', etc.).

        Returns:
            Dict with 'content' key containing the learning data, or None.
        """
        raise NotImplementedError

    @abstractmethod
    async def upsert_learning(
        self,
        id: str,
        learning_type: str,
        content: Dict[str, Any],
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Async insert or update a learning record.

        Args:
            id: Unique identifier for the learning.
            learning_type: Type of learning ('user_profile', 'session_context', etc.)
            content: The learning content as a dict.
            user_id: Associated user ID.
            agent_id: Associated agent ID.
            team_id: Associated team ID.
            session_id: Associated session ID.
            namespace: Namespace for scoping ('user', 'global', or custom).
            entity_id: Associated entity ID (for entity-specific learnings).
            entity_type: Entity type ('person', 'company', etc.).
            metadata: Optional metadata.
        """
        raise NotImplementedError

    @abstractmethod
    async def delete_learning(self, id: str) -> bool:
        """Async delete a learning record.

        Args:
            id: The learning ID to delete.

        Returns:
            True if deleted, False otherwise.
        """
        raise NotImplementedError

    @abstractmethod
    async def get_learnings(
        self,
        learning_type: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Async get multiple learning records.

        Args:
            learning_type: Filter by learning type.
            user_id: Filter by user ID.
            agent_id: Filter by agent ID.
            team_id: Filter by team ID.
            session_id: Filter by session ID.
            namespace: Filter by namespace ('user', 'global', or custom).
            entity_id: Filter by entity ID (for entity-specific learnings).
            entity_type: Filter by entity type ('person', 'company', etc.).
            limit: Maximum number of records to return.

        Returns:
            List of learning records.
        """
        raise NotImplementedError

    # --- Schedules (Optional) ---
    # These methods are optional. Override in subclasses to enable scheduler persistence.

    async def get_schedule(self, schedule_id: str) -> Optional[Dict[str, Any]]:
        """Get a schedule by ID."""
        raise NotImplementedError

    async def get_schedule_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a schedule by name."""
        raise NotImplementedError

    async def get_schedules(
        self,
        enabled: Optional[bool] = None,
        limit: int = 100,
        page: int = 1,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """List schedules with optional filtering.

        Returns:
            Tuple of (schedules, total_count)
        """
        raise NotImplementedError

    async def create_schedule(self, schedule_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new schedule."""
        raise NotImplementedError

    async def update_schedule(self, schedule_id: str, **kwargs: Any) -> Optional[Dict[str, Any]]:
        """Update a schedule by ID."""
        raise NotImplementedError

    async def delete_schedule(self, schedule_id: str) -> bool:
        """Delete a schedule and its associated runs."""
        raise NotImplementedError

    async def claim_due_schedule(self, worker_id: str, lock_grace_seconds: int = 300) -> Optional[Dict[str, Any]]:
        """Atomically claim a due schedule for execution."""
        raise NotImplementedError

    async def release_schedule(self, schedule_id: str, next_run_at: Optional[int] = None) -> bool:
        """Release a claimed schedule and optionally update next_run_at."""
        raise NotImplementedError

    # --- Schedule Runs (Optional) ---

    async def create_schedule_run(self, run_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a schedule run record."""
        raise NotImplementedError

    async def update_schedule_run(self, schedule_run_id: str, **kwargs: Any) -> Optional[Dict[str, Any]]:
        """Update a schedule run record."""
        raise NotImplementedError

    async def get_schedule_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Get a schedule run by ID."""
        raise NotImplementedError

    async def get_schedule_runs(
        self,
        schedule_id: str,
        limit: int = 20,
        page: int = 1,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """List runs for a schedule.

        Returns:
            Tuple of (runs, total_count)
        """
        raise NotImplementedError

    # --- Approvals (Optional) ---
    # These methods are optional. Override in subclasses to enable approval persistence.

    async def create_approval(self, approval_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create an approval record."""
        raise NotImplementedError

    async def get_approval(self, approval_id: str) -> Optional[Dict[str, Any]]:
        """Get an approval by ID."""
        raise NotImplementedError

    async def get_approvals(
        self,
        status: Optional[str] = None,
        source_type: Optional[str] = None,
        approval_type: Optional[str] = None,
        pause_type: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        user_id: Optional[str] = None,
        schedule_id: Optional[str] = None,
        run_id: Optional[str] = None,
        limit: int = 100,
        page: int = 1,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """List approvals with optional filtering. Returns (items, total_count)."""
        raise NotImplementedError

    async def update_approval(
        self, approval_id: str, expected_status: Optional[str] = None, **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        """Update an approval. If expected_status is set, only updates if current status matches (atomic guard)."""
        raise NotImplementedError

    async def delete_approval(self, approval_id: str) -> bool:
        """Delete an approval by ID."""
        raise NotImplementedError

    async def get_pending_approval_count(self, user_id: Optional[str] = None) -> int:
        """Get count of pending approvals."""
        raise NotImplementedError
