"""User-scoped database adapters for per-user data isolation.

These adapters wrap a BaseDb or AsyncBaseDb and automatically inject
``user_id`` into queries that support it. This ensures per-user data
isolation structurally — endpoints cannot accidentally omit user_id
filtering.

Usage:
    # In middleware:
    scoped_db = UserScopedDbAdapter(db, user_id="user-123")
    request.state.scoped_db = scoped_db

    # In endpoint:
    db = request.state.scoped_db  # all queries auto-filtered by user_id
    sessions = db.get_sessions(session_type=SessionType.AGENT)
    # ^ user_id="user-123" is injected automatically

    # System/admin code uses the unwrapped db directly:
    all_sessions = db._db.get_sessions(session_type=SessionType.AGENT)
"""

from typing import TYPE_CHECKING, Iterable, List, TypeVar

if TYPE_CHECKING:
    from agno.tracing.schemas import Span, Trace

from agno.db.base import AsyncBaseDb, BaseDb, SessionType
from agno.db.schemas import UserMemory
from agno.session import Session
from agno.utils.log import log_warning

_TUserIdCarrier = TypeVar("_TUserIdCarrier")


def _coerce_user_id(entity: _TUserIdCarrier, expected_user_id: str, kind: str) -> _TUserIdCarrier:
    """Force ``entity.user_id`` to ``expected_user_id``, warning on mismatch.

    The scoped adapters only ever exist for non-admin callers, so any
    upsert carrying a different user_id is either a bug or an attempted
    cross-user write. Rewriting the field keeps the data safe; the warning
    makes the misuse noisy during development.
    """
    current = getattr(entity, "user_id", None)
    if current is not None and current != expected_user_id:
        log_warning(
            f"UserScopedDbAdapter: {kind} arrived with user_id={current!r} but the adapter is bound to "
            f"user_id={expected_user_id!r}. Coercing to the bound user_id."
        )
    try:
        entity.user_id = expected_user_id  # type: ignore[attr-defined]
    except AttributeError:
        # Immutable carrier — caller is on their own; fall back to warning only.
        log_warning(f"UserScopedDbAdapter: unable to coerce user_id on {kind} ({type(entity).__name__})")
    return entity


def _coerce_all(entities: Iterable[_TUserIdCarrier], expected_user_id: str, kind: str) -> List[_TUserIdCarrier]:
    return [_coerce_user_id(e, expected_user_id, kind) for e in entities]


class UserScopedDbAdapter:
    """Adapts a BaseDb by injecting user_id into all user-scoped queries.

    Methods on tables WITHOUT user_id columns (knowledge, metrics, evals,
    components, schedules, spans, culture) delegate directly without modification.

    Methods on tables WITH user_id columns that this adapter explicitly
    overrides — sessions, memory, traces — force the scoped user_id and
    ignore any user_id passed by the caller. Approvals are NOT overridden
    here; the approval router enforces user_id at the route layer instead,
    and approval calls fall through ``__getattr__`` to the underlying db.
    """

    is_user_scoped = True
    is_async_db = False

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
        return self._db.delete_session(session_id=session_id, **kwargs)

    def delete_sessions(self, session_ids: List[str], **kwargs) -> None:
        kwargs["user_id"] = self._user_id
        return self._db.delete_sessions(session_ids=session_ids, **kwargs)

    def get_session(self, session_id: str, session_type: SessionType, **kwargs):
        kwargs["user_id"] = self._user_id
        return self._db.get_session(session_id=session_id, session_type=session_type, **kwargs)

    def get_sessions(self, session_type: SessionType, **kwargs):
        kwargs["user_id"] = self._user_id
        return self._db.get_sessions(session_type=session_type, **kwargs)

    def rename_session(self, session_id: str, session_type: SessionType, session_name: str, **kwargs):
        kwargs["user_id"] = self._user_id
        return self._db.rename_session(
            session_id=session_id, session_type=session_type, session_name=session_name, **kwargs
        )

    def upsert_session(self, session: Session, **kwargs):
        session = _coerce_user_id(session, self._user_id, "session")
        return self._db.upsert_session(session, **kwargs)

    def upsert_sessions(self, sessions: List[Session], **kwargs):
        sessions = _coerce_all(sessions, self._user_id, "session")
        return self._db.upsert_sessions(sessions, **kwargs)

    # ------------------------------------------------------------------
    # Memory (user-scoped)
    # ------------------------------------------------------------------

    def clear_memories(self) -> None:
        return self._db.clear_memories()

    def delete_user_memory(self, memory_id: str, **kwargs) -> None:
        kwargs["user_id"] = self._user_id
        return self._db.delete_user_memory(memory_id=memory_id, **kwargs)

    def delete_user_memories(self, memory_ids: List[str], **kwargs) -> None:
        kwargs["user_id"] = self._user_id
        return self._db.delete_user_memories(memory_ids=memory_ids, **kwargs)

    def get_all_memory_topics(self, **kwargs) -> List[str]:
        kwargs["user_id"] = self._user_id
        return self._db.get_all_memory_topics(**kwargs)

    def get_user_memory(self, memory_id: str, **kwargs):
        kwargs["user_id"] = self._user_id
        return self._db.get_user_memory(memory_id=memory_id, **kwargs)

    def get_user_memories(self, **kwargs):
        kwargs["user_id"] = self._user_id
        return self._db.get_user_memories(**kwargs)

    def get_user_memory_stats(self, **kwargs):
        kwargs["user_id"] = self._user_id
        return self._db.get_user_memory_stats(**kwargs)

    def upsert_user_memory(self, memory: UserMemory, **kwargs):
        memory = _coerce_user_id(memory, self._user_id, "memory")
        return self._db.upsert_user_memory(memory, **kwargs)

    def upsert_memories(self, memories: List[UserMemory], **kwargs):
        memories = _coerce_all(memories, self._user_id, "memory")
        return self._db.upsert_memories(memories, **kwargs)

    # ------------------------------------------------------------------
    # Traces (user-scoped)
    # ------------------------------------------------------------------

    def upsert_trace(self, trace: "Trace") -> None:
        return self._db.upsert_trace(trace)

    def get_trace(self, **kwargs):
        # Not every backend's get_trace accepts user_id yet. Try with, then
        # fall back to a post-filter on the returned trace so isolation still
        # holds on older backends. When the backend does filter, this is a no-op.
        try:
            trace = self._db.get_trace(user_id=self._user_id, **kwargs)
        except TypeError:
            trace = self._db.get_trace(**kwargs)
        if trace is not None and getattr(trace, "user_id", None) != self._user_id:
            return None
        return trace

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


# Compatibility glue: existing OS routers and managers dispatch on
# isinstance(db, BaseDb). Registering the adapter as a virtual subclass keeps
# those sync paths working without pretending this is a true storage backend.
BaseDb.register(UserScopedDbAdapter)


class AsyncUserScopedDbAdapter:
    """Adapts an AsyncBaseDb by injecting user_id into all user-scoped queries."""

    is_user_scoped = True
    is_async_db = True

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
        return await self._db.delete_session(session_id=session_id, **kwargs)

    async def delete_sessions(self, session_ids: List[str], **kwargs) -> None:
        kwargs["user_id"] = self._user_id
        return await self._db.delete_sessions(session_ids=session_ids, **kwargs)

    async def get_session(self, session_id: str, session_type: SessionType, **kwargs):
        kwargs["user_id"] = self._user_id
        return await self._db.get_session(session_id=session_id, session_type=session_type, **kwargs)

    async def get_sessions(self, session_type: SessionType, **kwargs):
        kwargs["user_id"] = self._user_id
        return await self._db.get_sessions(session_type=session_type, **kwargs)

    async def rename_session(self, session_id: str, session_type: SessionType, session_name: str, **kwargs):
        kwargs["user_id"] = self._user_id
        return await self._db.rename_session(
            session_id=session_id, session_type=session_type, session_name=session_name, **kwargs
        )

    async def upsert_session(self, session: Session, **kwargs):
        session = _coerce_user_id(session, self._user_id, "session")
        return await self._db.upsert_session(session, **kwargs)

    async def upsert_sessions(self, sessions: List[Session], **kwargs):
        # AsyncBaseDb doesn't declare this method on the abstract base, but
        # concrete implementations do — delegate via duck-typing.
        sessions = _coerce_all(sessions, self._user_id, "session")
        return await self._db.upsert_sessions(sessions, **kwargs)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Memory (user-scoped)
    # ------------------------------------------------------------------

    async def clear_memories(self) -> None:
        return await self._db.clear_memories()

    async def delete_user_memory(self, memory_id: str, **kwargs) -> None:
        kwargs["user_id"] = self._user_id
        return await self._db.delete_user_memory(memory_id=memory_id, **kwargs)

    async def delete_user_memories(self, memory_ids: List[str], **kwargs) -> None:
        kwargs["user_id"] = self._user_id
        return await self._db.delete_user_memories(memory_ids=memory_ids, **kwargs)

    async def get_all_memory_topics(self, **kwargs) -> List[str]:
        kwargs["user_id"] = self._user_id
        return await self._db.get_all_memory_topics(**kwargs)

    async def get_user_memory(self, memory_id: str, **kwargs):
        kwargs["user_id"] = self._user_id
        return await self._db.get_user_memory(memory_id=memory_id, **kwargs)

    async def get_user_memories(self, **kwargs):
        kwargs["user_id"] = self._user_id
        return await self._db.get_user_memories(**kwargs)

    async def get_user_memory_stats(self, **kwargs):
        kwargs["user_id"] = self._user_id
        return await self._db.get_user_memory_stats(**kwargs)

    async def upsert_user_memory(self, memory: UserMemory, **kwargs):
        memory = _coerce_user_id(memory, self._user_id, "memory")
        return await self._db.upsert_user_memory(memory, **kwargs)

    async def upsert_memories(self, memories: List[UserMemory], **kwargs):
        # AsyncBaseDb doesn't declare this method on the abstract base, but
        # concrete implementations do — delegate via duck-typing.
        memories = _coerce_all(memories, self._user_id, "memory")
        return await self._db.upsert_memories(memories, **kwargs)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Traces (user-scoped)
    # ------------------------------------------------------------------

    async def upsert_trace(self, trace: "Trace") -> None:
        return await self._db.upsert_trace(trace)

    async def get_trace(self, **kwargs):
        # See UserScopedDbAdapter.get_trace — backends that don't yet accept user_id
        # still get isolation via a post-filter on the returned trace.
        try:
            trace = await self._db.get_trace(user_id=self._user_id, **kwargs)
        except TypeError:
            trace = await self._db.get_trace(**kwargs)
        if trace is not None and getattr(trace, "user_id", None) != self._user_id:
            return None
        return trace

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


# Compatibility glue: existing OS routers and managers dispatch on
# isinstance(db, AsyncBaseDb). Registering the adapter as a virtual subclass
# keeps those async paths working without pretending this is a true storage backend.
AsyncBaseDb.register(AsyncUserScopedDbAdapter)


def is_user_scoped_db(db: object) -> bool:
    """Return True when ``db`` is a user-scoped adapter.

    Prefer this marker check over concrete class checks so future scoped DB
    adapters don't need every router to know their class names.
    """
    return getattr(db, "is_user_scoped", False) is True
