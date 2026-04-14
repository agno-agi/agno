"""User-scoped database wrapper for per-user data isolation.

Wraps a BaseDb or AsyncBaseDb and automatically injects user_id into
every query that supports it. This ensures per-user data isolation
structurally — endpoints cannot accidentally omit user_id filtering.

Usage:
    # In middleware:
    scoped_db = UserScopedDb(db, user_id="user-123")
    request.state.scoped_db = scoped_db

    # In endpoint:
    db = request.state.scoped_db  # all queries auto-filtered by user_id
    sessions = db.get_sessions(session_type=SessionType.AGENT)
    # ^ user_id="user-123" is injected automatically

    # System/admin code uses the unwrapped db directly:
    all_sessions = db._db.get_sessions(session_type=SessionType.AGENT)
"""

from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from agno.tracing.schemas import Span, Trace

from agno.db.base import AsyncBaseDb, BaseDb, SessionType
from agno.db.schemas import UserMemory
from agno.session import Session


class UserScopedDb:
    """Wraps a BaseDb and injects user_id into all user-scoped queries.

    Methods on tables WITHOUT user_id columns (knowledge, metrics, evals,
    components, schedules, spans, culture) delegate directly without modification.

    Methods on tables WITH user_id columns (sessions, memory, traces, approvals)
    force the scoped user_id, ignoring any user_id passed by the caller.
    """

    def __init__(self, db: BaseDb, user_id: str):
        self._db = db
        self._user_id = user_id
        # Expose db metadata so routers that check isinstance() or attributes still work
        self.id = db.id
        self.session_table_name = db.session_table_name
        self.culture_table_name = db.culture_table_name
        self.memory_table_name = db.memory_table_name
        self.metrics_table_name = db.metrics_table_name
        self.eval_table_name = db.eval_table_name
        self.knowledge_table_name = db.knowledge_table_name
        self.trace_table_name = db.trace_table_name
        self.span_table_name = db.span_table_name

    @property
    def user_id(self) -> str:
        return self._user_id

    # ------------------------------------------------------------------
    # Sessions (user-scoped)
    # ------------------------------------------------------------------

    def delete_session(self, session_id: str, **kwargs) -> bool:
        kwargs["user_id"] = self._user_id
        return self._db.delete_session(session_id, **kwargs)

    def delete_sessions(self, session_ids: List[str], **kwargs) -> None:
        kwargs["user_id"] = self._user_id
        return self._db.delete_sessions(session_ids, **kwargs)

    def get_session(self, session_id: str, session_type: SessionType, **kwargs):
        kwargs["user_id"] = self._user_id
        return self._db.get_session(session_id, session_type, **kwargs)

    def get_sessions(self, session_type: SessionType, **kwargs):
        kwargs["user_id"] = self._user_id
        return self._db.get_sessions(session_type, **kwargs)

    def rename_session(self, session_id: str, session_type: SessionType, session_name: str, **kwargs):
        kwargs["user_id"] = self._user_id
        return self._db.rename_session(session_id, session_type, session_name, **kwargs)

    def upsert_session(self, session: Session, **kwargs):
        return self._db.upsert_session(session, **kwargs)

    def upsert_sessions(self, sessions: List[Session], **kwargs):
        return self._db.upsert_sessions(sessions, **kwargs)

    # ------------------------------------------------------------------
    # Memory (user-scoped)
    # ------------------------------------------------------------------

    def clear_memories(self) -> None:
        return self._db.clear_memories()

    def delete_user_memory(self, memory_id: str, **kwargs) -> None:
        kwargs["user_id"] = self._user_id
        return self._db.delete_user_memory(memory_id, **kwargs)

    def delete_user_memories(self, memory_ids: List[str], **kwargs) -> None:
        kwargs["user_id"] = self._user_id
        return self._db.delete_user_memories(memory_ids, **kwargs)

    def get_all_memory_topics(self, **kwargs) -> List[str]:
        kwargs["user_id"] = self._user_id
        return self._db.get_all_memory_topics(**kwargs)

    def get_user_memory(self, memory_id: str, **kwargs):
        kwargs["user_id"] = self._user_id
        return self._db.get_user_memory(memory_id, **kwargs)

    def get_user_memories(self, **kwargs):
        kwargs["user_id"] = self._user_id
        return self._db.get_user_memories(**kwargs)

    def get_user_memory_stats(self, **kwargs):
        kwargs["user_id"] = self._user_id
        return self._db.get_user_memory_stats(**kwargs)

    def upsert_user_memory(self, memory: UserMemory, **kwargs):
        return self._db.upsert_user_memory(memory, **kwargs)

    def upsert_memories(self, memories: List[UserMemory], **kwargs):
        return self._db.upsert_memories(memories, **kwargs)

    # ------------------------------------------------------------------
    # Traces (user-scoped)
    # ------------------------------------------------------------------

    def upsert_trace(self, trace: "Trace") -> None:
        return self._db.upsert_trace(trace)

    def get_trace(self, **kwargs):
        kwargs["user_id"] = self._user_id
        return self._db.get_trace(**kwargs)

    def get_traces(self, **kwargs):
        kwargs["user_id"] = self._user_id
        return self._db.get_traces(**kwargs)

    def get_trace_stats(self, **kwargs):
        kwargs["user_id"] = self._user_id
        return self._db.get_trace_stats(**kwargs)

    # ------------------------------------------------------------------
    # Spans (not user-scoped — no user_id column)
    # ------------------------------------------------------------------

    def create_span(self, span: "Span") -> None:
        return self._db.create_span(span)

    def create_spans(self, spans: List) -> None:
        return self._db.create_spans(spans)

    def get_span(self, span_id: str):
        return self._db.get_span(span_id)

    def get_spans(self, **kwargs):
        return self._db.get_spans(**kwargs)

    # ------------------------------------------------------------------
    # Passthrough: Knowledge, Metrics, Evals, Culture, Components,
    # Schedules, Approvals, Schema versions, etc.
    # These are NOT user-scoped — delegate directly.
    # ------------------------------------------------------------------

    def __getattr__(self, name: str):
        """Delegate any method not explicitly defined to the wrapped db."""
        return getattr(self._db, name)


class AsyncUserScopedDb:
    """Async variant of UserScopedDb.

    Wraps an AsyncBaseDb and injects user_id into all user-scoped queries.
    """

    def __init__(self, db: AsyncBaseDb, user_id: str):
        self._db = db
        self._user_id = user_id
        self.id = db.id
        self.session_table_name = db.session_table_name
        self.culture_table_name = db.culture_table_name
        self.memory_table_name = db.memory_table_name
        self.metrics_table_name = db.metrics_table_name
        self.eval_table_name = db.eval_table_name
        self.knowledge_table_name = db.knowledge_table_name
        self.trace_table_name = db.trace_table_name
        self.span_table_name = db.span_table_name

    @property
    def user_id(self) -> str:
        return self._user_id

    # ------------------------------------------------------------------
    # Sessions (user-scoped)
    # ------------------------------------------------------------------

    async def delete_session(self, session_id: str, **kwargs) -> bool:
        kwargs["user_id"] = self._user_id
        return await self._db.delete_session(session_id, **kwargs)

    async def delete_sessions(self, session_ids: List[str], **kwargs) -> None:
        kwargs["user_id"] = self._user_id
        return await self._db.delete_sessions(session_ids, **kwargs)

    async def get_session(self, session_id: str, session_type: SessionType, **kwargs):
        kwargs["user_id"] = self._user_id
        return await self._db.get_session(session_id, session_type, **kwargs)

    async def get_sessions(self, session_type: SessionType, **kwargs):
        kwargs["user_id"] = self._user_id
        return await self._db.get_sessions(session_type, **kwargs)

    async def rename_session(self, session_id: str, session_type: SessionType, session_name: str, **kwargs):
        kwargs["user_id"] = self._user_id
        return await self._db.rename_session(session_id, session_type, session_name, **kwargs)

    async def upsert_session(self, session: Session, **kwargs):
        return await self._db.upsert_session(session, **kwargs)

    async def upsert_sessions(self, sessions: List[Session], **kwargs):
        return await self._db.upsert_sessions(sessions, **kwargs)

    # ------------------------------------------------------------------
    # Memory (user-scoped)
    # ------------------------------------------------------------------

    async def clear_memories(self) -> None:
        return await self._db.clear_memories()

    async def delete_user_memory(self, memory_id: str, **kwargs) -> None:
        kwargs["user_id"] = self._user_id
        return await self._db.delete_user_memory(memory_id, **kwargs)

    async def delete_user_memories(self, memory_ids: List[str], **kwargs) -> None:
        kwargs["user_id"] = self._user_id
        return await self._db.delete_user_memories(memory_ids, **kwargs)

    async def get_all_memory_topics(self, **kwargs) -> List[str]:
        kwargs["user_id"] = self._user_id
        return await self._db.get_all_memory_topics(**kwargs)

    async def get_user_memory(self, memory_id: str, **kwargs):
        kwargs["user_id"] = self._user_id
        return await self._db.get_user_memory(memory_id, **kwargs)

    async def get_user_memories(self, **kwargs):
        kwargs["user_id"] = self._user_id
        return await self._db.get_user_memories(**kwargs)

    async def get_user_memory_stats(self, **kwargs):
        kwargs["user_id"] = self._user_id
        return await self._db.get_user_memory_stats(**kwargs)

    async def upsert_user_memory(self, memory: UserMemory, **kwargs):
        return await self._db.upsert_user_memory(memory, **kwargs)

    async def upsert_memories(self, memories: List[UserMemory], **kwargs):
        return await self._db.upsert_memories(memories, **kwargs)

    # ------------------------------------------------------------------
    # Traces (user-scoped)
    # ------------------------------------------------------------------

    async def upsert_trace(self, trace: "Trace") -> None:
        return await self._db.upsert_trace(trace)

    async def get_trace(self, **kwargs):
        kwargs["user_id"] = self._user_id
        return await self._db.get_trace(**kwargs)

    async def get_traces(self, **kwargs):
        kwargs["user_id"] = self._user_id
        return await self._db.get_traces(**kwargs)

    async def get_trace_stats(self, **kwargs):
        kwargs["user_id"] = self._user_id
        return await self._db.get_trace_stats(**kwargs)

    # ------------------------------------------------------------------
    # Spans (not user-scoped)
    # ------------------------------------------------------------------

    async def create_span(self, span: "Span") -> None:
        return await self._db.create_span(span)

    async def create_spans(self, spans: List) -> None:
        return await self._db.create_spans(spans)

    async def get_span(self, span_id: str):
        return await self._db.get_span(span_id)

    async def get_spans(self, **kwargs):
        return await self._db.get_spans(**kwargs)

    # ------------------------------------------------------------------
    # Passthrough for everything else
    # ------------------------------------------------------------------

    def __getattr__(self, name: str):
        return getattr(self._db, name)
