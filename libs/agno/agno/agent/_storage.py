"""Database persistence and serialization helpers for Agent."""

from __future__ import annotations

import re
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Optional,
    Set,
    Type,
    Union,
    cast,
)

from pydantic import BaseModel

if TYPE_CHECKING:
    from agno.agent.agent import Agent
    from agno.offload.store import ResultStore

from agno.db.base import BaseDb, ComponentType, SessionType
from agno.db.schemas.scheduler import strip_reserved_run_metadata
from agno.db.utils import resolve_db_from_config
from agno.exceptions import ComponentRehydrationError
from agno.metrics import RunMetrics, SessionMetrics
from agno.models.base import Model
from agno.models.message import Message
from agno.registry.registry import Registry, _memory_manager_resource_name
from agno.run.agent import RunOutput
from agno.session import AgentSession, TeamSession, WorkflowSession
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit
from agno.utils.agent import (
    aget_last_run_output_util,
    aget_run_output_util,
    get_last_run_output_util,
    get_run_output_util,
)
from agno.utils.db_fallback import require_db_fallback_matches
from agno.utils.log import log_debug, log_error, log_warning
from agno.utils.merge_dict import merge_dictionaries
from agno.utils.string import generate_id_from_name

# MemoryManager.__init__ (agno/memory/manager.py) auto-generates
# ``memory_manager_<8 hex>`` when no id is passed. Such an id is minted fresh
# every process, so a config carrying it can never resolve against a registry
# in a new process; it must not be written as a registry reference.
_AUTO_MEMORY_MANAGER_ID_RE = re.compile(r"memory_manager_[0-9a-f]{8}")


def is_auto_generated_memory_manager_id(manager_id: Any) -> bool:
    """True when the id has the shape MemoryManager auto-generates per instance."""
    return isinstance(manager_id, str) and _AUTO_MEMORY_MANAGER_ID_RE.fullmatch(manager_id) is not None


# Keys a serialized memory_manager reference can carry. to_dict writes
# ``registry_id``; a config authored against the registry listing carries the
# resource's ``id`` or ``name`` the way a knowledge reference does. A bare
# string is the id itself.
_MEMORY_MANAGER_REF_KEYS = ("registry_id", "id", "name")


def _memory_manager_ref_keys(manager_ref: Any) -> List[str]:
    """Every registry key a serialized memory_manager reference carries.

    The registry listing emits both an id and a name for each manager, so a
    config authored from it carries both. Either one may be the key that still
    resolves in the process doing the load, so all of them are candidates.
    """
    if isinstance(manager_ref, str):
        return [manager_ref] if manager_ref else []
    if isinstance(manager_ref, dict):
        keys: List[str] = []
        for key in _MEMORY_MANAGER_REF_KEYS:
            value = manager_ref.get(key)
            if isinstance(value, str) and value and value not in keys:
                keys.append(value)
        return keys
    return []


def _competing_memory_manager_ids(registry: Registry, name: str) -> List[str]:
    """Ids of the registered managers a single listing name matches."""
    return [
        str(getattr(manager, "id", None))
        for manager in (registry.memory_managers or [])
        if _memory_manager_resource_name(manager) == name
    ]


def resolve_memory_manager_reference(
    config: Dict[str, Any],
    registry: Optional[Registry],
    strict: bool,
    component_label: str,
) -> None:
    """Replace ``config["memory_manager"]`` with the live instance it references.

    Agents and teams write and read the reference identically, so both call
    this. A reference that cannot be resolved is dropped, or refused under
    strict when dropping it would lose memory the component asked for.
    """
    manager_ref = config.get("memory_manager")
    if manager_ref is None:
        return

    ref_keys = _memory_manager_ref_keys(manager_ref)
    resolved_manager = None
    ambiguous_key: Optional[str] = None
    if registry is not None:
        # Keys are tried in priority order, and each is resolved as an id
        # before a name: within one key an id match beats a name match, but an
        # earlier key always outranks a later one. Resolving every key as an id
        # first would let the reference's name field outrank its own
        # registry_id whenever some unrelated manager's id equals that name.
        for key in ref_keys:
            resolved_manager = registry.get_memory_manager(key)
            if resolved_manager is not None:
                break
            if registry.memory_manager_name_is_ambiguous(key):
                # A name two distinct managers share could bind the wrong one.
                # A strict load leaves it unresolved so the remaining keys
                # decide; a lenient load stays lenient and takes the first
                # match, naming the managers that competed.
                if strict:
                    if ambiguous_key is None:
                        ambiguous_key = key
                    continue
                competing = ", ".join(_competing_memory_manager_ids(registry, key))
                log_warning(
                    f"Memory manager name '{key}' matches more than one registered manager "
                    f"({competing}); binding the first."
                )
            resolved_manager = registry.get_memory_manager_by_name(key)
            if resolved_manager is not None:
                break

    if resolved_manager is not None:
        config["memory_manager"] = resolved_manager
        return

    # A reference carrying nothing but an auto-generated id (written by configs
    # saved before ids were filtered) can never resolve in a new process, so
    # refusing on it would 422 the component forever. That escape is weighed
    # before any refusal, including the ambiguous-name one.
    #
    # There is deliberately no escape for "the component rebuilds a default
    # manager anyway": the serializer writes this reference ONLY for a manager
    # with a stable, deliberately-assigned id, so what a default rebuild
    # produces is a different manager - the agent's own model, no capture
    # instructions - writing memories under rules nobody asked for, while the
    # caller is told the load succeeded. A missing model, knowledge or tool
    # reference refuses on this same path; so does this one.
    only_auto_ids = bool(ref_keys) and all(is_auto_generated_memory_manager_id(key) for key in ref_keys)
    tried = " or ".join(f"'{key}'" for key in ref_keys) if ref_keys else repr(manager_ref)
    if strict and not only_auto_ids:
        if ambiguous_key is not None:
            raise ComponentRehydrationError(
                f"{component_label} references memory manager '{ambiguous_key}', but two distinct "
                "managers are registered under that name, so the reference could bind the "
                "wrong manager. Give the managers distinct names."
            )
        raise ComponentRehydrationError(
            f"{component_label} references memory manager {tried} which was not "
            "found in the registry. Register the manager in the process serving the component, or "
            "pass strict=False to load the component without it."
        )
    if ambiguous_key is not None:
        log_warning(
            f"Memory manager name '{ambiguous_key}' matches two distinct registered managers; "
            "loading the component without it."
        )
    else:
        log_warning(f"Memory manager {tried} not found in registry; loading the component without it.")
    config.pop("memory_manager", None)


def is_learning_reference(value: Any) -> bool:
    """True for the shape to_dict writes for a registry-declared machine.

    A reference is ``{"name": <non-empty str>}`` and nothing else. ``{}`` and
    any dict carrying a store or knob key is an inline machine config, which
    LearningMachine.from_dict rebuilds; that includes every config written
    before machines had names.
    """
    if not isinstance(value, dict) or set(value) != {"name"}:
        return False
    name = value.get("name")
    return isinstance(name, str) and bool(name)


def resolve_learning_reference(
    config: Dict[str, Any],
    registry: Optional[Registry],
    strict: bool,
    component_label: str,
) -> None:
    """Replace a ``config["learning"]`` reference with the registered machine.

    Agents and teams write and read the reference identically, so both call
    this. An inline machine config is left for LearningMachine.from_dict. A
    reference that cannot be resolved is dropped, or refused under strict:
    the registry is what a stored component's learning resolves through, so
    loading without it would silently run the component with no learning.
    """
    reference = config.get("learning")
    if not isinstance(reference, dict) or not is_learning_reference(reference):
        return
    name = reference["name"]

    if registry is not None:
        if registry.learning_name_is_ambiguous(name):
            # A name two distinct machines share could bind the wrong one. A
            # strict load refuses; a lenient load stays lenient and takes the
            # first registered, saying so.
            if strict:
                raise ComponentRehydrationError(
                    f"{component_label} references learning machine '{name}', but two distinct "
                    "machines are registered under that name, so the reference could bind the "
                    "wrong machine. Give the machines distinct names."
                )
            log_warning(f"Learning machine name '{name}' matches more than one registered machine; binding the first.")
        machine = registry.get_learning(name)
        if machine is not None:
            config["learning"] = machine
            return

    if strict:
        raise ComponentRehydrationError(
            f"{component_label} references learning machine '{name}' which was not found in the "
            "registry. Register the machine in the process serving the component, or pass "
            "strict=False to load the component without it."
        )
    log_warning(f"Learning machine '{name}' not found in registry; loading the component without it.")
    config.pop("learning", None)


# ---------------------------------------------------------------------------
# Run output accessors
# ---------------------------------------------------------------------------


def _offload_to_config(value: Any) -> Union[bool, Dict[str, Any]]:
    """The offload_tool_results setting as it is stored: True, False, or the ResultStore settings."""
    from agno.offload.store import ResultStore

    if value is True or value is False:
        return value
    if isinstance(value, ResultStore):
        return value.to_dict()
    raise TypeError(
        "offload_tool_results must be True, False, None or a ResultStore; set the threshold with ResultStore(threshold_chars=...)."
    )


def _offload_from_config(value: Any) -> Optional[Union[bool, "ResultStore"]]:
    """The offload_tool_results setting from a stored config: unset, True, False, or a ResultStore."""
    if value is None:
        return None
    if isinstance(value, dict):
        from agno.offload.store import ResultStore

        return ResultStore.from_dict(value)
    return bool(value)


def get_run_output(
    agent: Agent, run_id: str, session_id: Optional[str] = None, user_id: Optional[str] = None
) -> Optional[RunOutput]:
    """
    Get a RunOutput from the database.

    Args:
        agent: The Agent instance.
        run_id (str): The run_id to load from storage.
        session_id (Optional[str]): The session_id to load from storage.
        user_id (Optional[str]): The user_id to scope the session lookup.
    Returns:
        Optional[RunOutput]: The RunOutput from the database or None if not found.
    """
    if not session_id and not agent.session_id:
        raise Exception("No session_id provided")

    session_id_to_load = session_id or agent.session_id
    return cast(RunOutput, get_run_output_util(agent, run_id=run_id, session_id=session_id_to_load, user_id=user_id))


async def aget_run_output(
    agent: Agent, run_id: str, session_id: Optional[str] = None, user_id: Optional[str] = None
) -> Optional[RunOutput]:
    """
    Get a RunOutput from the database.

    Args:
        agent: The Agent instance.
        run_id (str): The run_id to load from storage.
        session_id (Optional[str]): The session_id to load from storage.
        user_id (Optional[str]): The user_id to scope the session lookup.
    Returns:
        Optional[RunOutput]: The RunOutput from the database or None if not found.
    """
    if not session_id and not agent.session_id:
        raise Exception("No session_id provided")

    session_id_to_load = session_id or agent.session_id
    return cast(
        RunOutput, await aget_run_output_util(agent, run_id=run_id, session_id=session_id_to_load, user_id=user_id)
    )


def get_last_run_output(agent: Agent, session_id: Optional[str] = None) -> Optional[RunOutput]:
    """
    Get the last run response from the database.

    Args:
        agent: The Agent instance.
        session_id (Optional[str]): The session_id to load from storage.

    Returns:
        Optional[RunOutput]: The last run response from the database or None if not found.
    """
    if not session_id and not agent.session_id:
        raise Exception("No session_id provided")

    session_id_to_load = session_id or agent.session_id
    return cast(RunOutput, get_last_run_output_util(agent, session_id=session_id_to_load))


async def aget_last_run_output(agent: Agent, session_id: Optional[str] = None) -> Optional[RunOutput]:
    """
    Get the last run response from the database.

    Args:
        agent: The Agent instance.
        session_id (Optional[str]): The session_id to load from storage.

    Returns:
        Optional[RunOutput]: The last run response from the database or None if not found.
    """
    if not session_id and not agent.session_id:
        raise Exception("No session_id provided")

    session_id_to_load = session_id or agent.session_id
    return cast(RunOutput, await aget_last_run_output_util(agent, session_id=session_id_to_load))


# ---------------------------------------------------------------------------
# Session I/O (low-level DB calls)
# ---------------------------------------------------------------------------


def read_session(
    agent: Agent,
    session_id: str,
    session_type: SessionType = SessionType.AGENT,
    user_id: Optional[str] = None,
    runs_limit: Optional[int] = None,
) -> Optional[Union[AgentSession, TeamSession, WorkflowSession]]:
    """Get a Session from the database.

    Read errors propagate. Do NOT coerce failures to None here: an empty result
    is indistinguishable from "row does not exist", and the caller will happily
    create a fresh session with the same id and overwrite the real row on the
    next write. This is how a transient Postgres failover wiped six weeks of
    conversation history in a real incident. Let the exception surface and
    fail the run loudly -- a failed run is recoverable, a wiped session is not.
    """
    if not agent.db:
        raise ValueError("Db not initialized")
    # Every adapter accepts runs_limit; those that don't optimize it load the full
    # history (a safe superset), so we can pass it unconditionally.
    return agent.db.get_session(  # type: ignore
        session_id=session_id, session_type=session_type, user_id=user_id, runs_limit=runs_limit
    )


async def aread_session(
    agent: Agent,
    session_id: str,
    session_type: SessionType = SessionType.AGENT,
    user_id: Optional[str] = None,
    runs_limit: Optional[int] = None,
) -> Optional[Union[AgentSession, TeamSession, WorkflowSession]]:
    """Async twin of :func:`read_session`. Same rationale: do NOT swallow errors."""
    from agno.agent import _init

    if not agent.db:
        raise ValueError("Db not initialized")
    # Every adapter accepts runs_limit; those that don't optimize it load the full
    # history (a safe superset), so we can pass it unconditionally.
    if _init.has_async_db(agent):
        return await agent.db.get_session(  # type: ignore
            session_id=session_id, session_type=session_type, user_id=user_id, runs_limit=runs_limit
        )
    return agent.db.get_session(  # type: ignore
        session_id=session_id, session_type=session_type, user_id=user_id, runs_limit=runs_limit
    )


def upsert_session(
    agent: Agent, session: Union[AgentSession, TeamSession, WorkflowSession]
) -> Optional[Union[AgentSession, TeamSession, WorkflowSession]]:
    """Upsert the session row.

    Runs are persisted independently via ``upsert_run()`` — this writes only the
    session row.

    Args:
        agent: The Agent instance.
        session: The session to upsert.
    """

    try:
        if not agent.db:
            raise ValueError("Db not initialized")
        return agent.db.upsert_session(session=session)  # type: ignore
    except Exception as e:
        import traceback

        traceback.print_exc(limit=3)
        log_warning(f"Error upserting session into db: {str(e)}")
        return None


async def aupsert_session(
    agent: Agent, session: Union[AgentSession, TeamSession, WorkflowSession]
) -> Optional[Union[AgentSession, TeamSession, WorkflowSession]]:
    """Upsert the session row.

    Runs are persisted independently via ``upsert_run()`` — this writes only the
    session row.

    Args:
        agent: The Agent instance.
        session: The session to upsert.
    """
    from agno.agent import _init

    try:
        if not agent.db:
            raise ValueError("Db not initialized")
        if _init.has_async_db(agent):
            return await agent.db.upsert_session(session=session)  # type: ignore
        else:
            return agent.db.upsert_session(session=session)  # type: ignore
    except Exception as e:
        import traceback

        traceback.print_exc(limit=3)
        log_warning(f"Error upserting session into db: {str(e)}")
        return None


def upsert_run(
    agent: Agent,
    run: RunOutput,
    session_id: str,
    user_id: Optional[str] = None,
    run_index: Optional[int] = None,
) -> None:
    """Upsert a single run to the database (O(1) operation).

    This is optimized for updating existing runs (e.g., status changes in HITL
    or background mode) without re-upserting all runs in the session.

    Silently no-ops on adapters that have not been ported to v3 storage —
    those adapters persist runs inline via ``upsert_session``.

    Args:
        agent: The Agent instance.
        run: The run to upsert.
        session_id: The session ID this run belongs to.
        user_id: Optional user ID to associate with the run.
        run_index: Optional run index for new runs.
    """
    try:
        if not agent.db:
            return
        from agno.run.status_persist import persist_worker_owned_run

        # Queue-worker-owned runs save through the attempt-fenced primitive;
        # a zombie attempt's write is refused instead of clobbering the row
        if persist_worker_owned_run(agent.db, run, session_id=session_id, user_id=user_id):
            return
        agent.db.upsert_run(run=run, session_id=session_id, user_id=user_id, run_index=run_index)  # type: ignore[union-attr]
    except NotImplementedError:
        # Adapter has not been ported to v3 storage; runs are persisted inline
        # via upsert_session instead. Silent no-op.
        log_debug(f"{type(agent.db).__name__} does not implement upsert_run; skipping per-run write")
    except Exception as e:
        import traceback

        traceback.print_exc(limit=3)
        log_warning(f"Error upserting run into db: {str(e)}")


async def aupsert_run(
    agent: Agent,
    run: RunOutput,
    session_id: str,
    user_id: Optional[str] = None,
    run_index: Optional[int] = None,
) -> None:
    """Upsert a single run to the database (O(1) operation).

    This is the async version of upsert_run(). Optimized for updating existing
    runs (e.g., status changes in HITL or background mode) without re-upserting
    all runs in the session.

    Silently no-ops on adapters that have not been ported to v3 storage —
    those adapters persist runs inline via ``upsert_session``.

    Args:
        agent: The Agent instance.
        run: The run to upsert.
        session_id: The session ID this run belongs to.
        user_id: Optional user ID to associate with the run.
        run_index: Optional run index for new runs.
    """
    from agno.agent import _init

    try:
        if not agent.db:
            return
        from agno.run.status_persist import apersist_worker_owned_run

        # Queue-worker-owned runs save through the attempt-fenced primitive;
        # a zombie attempt's write is refused instead of clobbering the row
        if await apersist_worker_owned_run(agent.db, run, session_id=session_id, user_id=user_id):
            return
        if _init.has_async_db(agent):
            await agent.db.upsert_run(run=run, session_id=session_id, user_id=user_id, run_index=run_index)  # type: ignore[union-attr,misc]
        else:
            agent.db.upsert_run(run=run, session_id=session_id, user_id=user_id, run_index=run_index)  # type: ignore[union-attr]
    except NotImplementedError:
        log_debug(f"{type(agent.db).__name__} does not implement upsert_run; skipping per-run write")
    except Exception as e:
        import traceback

        traceback.print_exc(limit=3)
        log_warning(f"Error upserting run into db: {str(e)}")


# ---------------------------------------------------------------------------
# Session state helpers
# ---------------------------------------------------------------------------


def load_session_state(agent: Agent, session: AgentSession, session_state: Dict[str, Any]):
    """Load and return the stored session_state from the database, optionally merging it with the given one"""

    # Get the session_state from the database and merge with proper precedence
    # At this point session_state contains: agent_defaults + run_params
    if session.session_data is not None and "session_state" in session.session_data:
        session_state_from_db = session.session_data.get("session_state")

        if (
            session_state_from_db is not None
            and isinstance(session_state_from_db, dict)
            and len(session_state_from_db) > 0
            and not agent.overwrite_db_session_state
        ):
            # This preserves precedence: run_params > db_state > agent_defaults
            merged_state = session_state_from_db.copy()
            merge_dictionaries(merged_state, session_state)
            session_state.clear()
            session_state.update(merged_state)

    # Update the session_state in the session
    if session.session_data is not None:
        session.session_data["session_state"] = session_state

    return session_state


def update_metadata(agent: Agent, session: AgentSession):
    """Merge the agent's metadata into the session's metadata.

    Agent metadata provides defaults; the session's own stored values win on
    conflict, matching resolve_run_options (agent < session), so a value set on
    the session is not overwritten by an agent default and persists across runs.
    Only the session is updated; the shared Agent instance is never mutated.
    """
    if session.metadata is not None and agent.metadata is not None:
        from copy import deepcopy

        merged = deepcopy(agent.metadata)
        merge_dictionaries(merged, session.metadata)
        session.metadata.clear()
        session.metadata.update(merged)


def get_session_metrics_internal(agent: Agent, session: AgentSession) -> SessionMetrics:
    # Get the session_metrics from the database
    if session.session_data is not None and "session_metrics" in session.session_data:
        session_metrics_from_db = session.session_data.get("session_metrics")
        if session_metrics_from_db is not None:
            if isinstance(session_metrics_from_db, dict):
                return SessionMetrics.from_dict(session_metrics_from_db)
            elif isinstance(session_metrics_from_db, SessionMetrics):
                return session_metrics_from_db
            elif isinstance(session_metrics_from_db, RunMetrics):
                # Convert legacy RunMetrics to SessionMetrics
                return SessionMetrics(
                    input_tokens=session_metrics_from_db.input_tokens,
                    output_tokens=session_metrics_from_db.output_tokens,
                    total_tokens=session_metrics_from_db.total_tokens,
                    audio_input_tokens=session_metrics_from_db.audio_input_tokens,
                    audio_output_tokens=session_metrics_from_db.audio_output_tokens,
                    audio_total_tokens=session_metrics_from_db.audio_total_tokens,
                    cache_read_tokens=session_metrics_from_db.cache_read_tokens,
                    cache_write_tokens=session_metrics_from_db.cache_write_tokens,
                    reasoning_tokens=session_metrics_from_db.reasoning_tokens,
                    cost=session_metrics_from_db.cost,
                )
    return SessionMetrics()


def update_session_metrics(agent: Agent, session: AgentSession, run_response: RunOutput) -> None:
    """Calculate session metrics - convert run Metrics to SessionMetrics."""
    session_metrics = get_session_metrics_internal(agent, session=session)
    # Add the metrics for the current run to the session metrics
    if session_metrics is None:
        return
    if run_response.metrics is not None:
        session_metrics.accumulate_from_run(run_response.metrics)

    if session.session_data is not None:
        session.session_data["session_metrics"] = session_metrics.to_dict()


def read_or_create_session(
    agent: Agent,
    session_id: str,
    user_id: Optional[str] = None,
) -> AgentSession:
    from time import time
    from uuid import uuid4

    # Returning cached session if we have one
    cached_session = agent._get_cached_session(session_id, user_id=user_id)
    if cached_session is not None:
        return cached_session

    # Try to load from database
    agent_session = None
    if agent.db is not None and agent.team_id is None and agent.workflow_id is None:
        log_debug(f"Reading AgentSession: {session_id}")

        agent_session = cast(AgentSession, read_session(agent, session_id=session_id, user_id=user_id))

    if agent_session is None:
        # Creating new session if none found
        log_debug(f"Creating new AgentSession: {session_id}")
        from copy import deepcopy

        session_data = {}
        if agent.session_state is not None:
            session_data["session_state"] = deepcopy(agent.session_state)
        agent_session = AgentSession(
            session_id=session_id,
            agent_id=agent.id,
            user_id=user_id,
            agent_data=get_agent_data(agent),
            session_data=session_data,
            # Copy so the session record never aliases the shared Agent's dict
            metadata=deepcopy(agent.metadata),
            created_at=int(time()),
        )
        if agent.introduction is not None:
            introduction_run = RunOutput(
                run_id=str(uuid4()),
                session_id=session_id,
                agent_id=agent.id,
                agent_name=agent.name,
                user_id=user_id,
                content=agent.introduction,
                messages=[
                    Message(role=agent.model.assistant_message_role, content=agent.introduction)  # type: ignore
                ],
            )
            agent_session.upsert_run(introduction_run)

            # v3: session.runs is in-memory; persist the intro to the runs table
            # so a session reload picks it up (pre-3.0's save_session wrote the
            # entire runs blob, so this happened for free).
            if agent.db is not None and agent.team_id is None and agent.workflow_id is None:
                from agno.agent._session import save_session
                from agno.agent._storage import upsert_run

                save_session(agent, session=agent_session)
                upsert_run(agent, run=introduction_run, session_id=session_id, user_id=user_id, run_index=0)

    if agent.cache_session:
        agent._set_cached_session(agent_session)

    return agent_session


async def aread_or_create_session(
    agent: Agent,
    session_id: str,
    user_id: Optional[str] = None,
) -> AgentSession:
    from time import time
    from uuid import uuid4

    from agno.agent import _init

    # Returning cached session if we have one
    cached_session = agent._get_cached_session(session_id, user_id=user_id)
    if cached_session is not None:
        return cached_session

    # Try to load from database
    agent_session = None
    if agent.db is not None and agent.team_id is None and agent.workflow_id is None:
        log_debug(f"Reading AgentSession: {session_id}")
        if _init.has_async_db(agent):
            agent_session = cast(AgentSession, await aread_session(agent, session_id=session_id, user_id=user_id))
        else:
            agent_session = cast(AgentSession, read_session(agent, session_id=session_id, user_id=user_id))

    if agent_session is None:
        # Creating new session if none found
        log_debug(f"Creating new AgentSession: {session_id}")
        from copy import deepcopy

        session_data = {}
        if agent.session_state is not None:
            session_data["session_state"] = deepcopy(agent.session_state)
        agent_session = AgentSession(
            session_id=session_id,
            agent_id=agent.id,
            user_id=user_id,
            agent_data=get_agent_data(agent),
            session_data=session_data,
            # Copy so the session record never aliases the shared Agent's dict
            metadata=deepcopy(agent.metadata),
            created_at=int(time()),
        )
        if agent.introduction is not None:
            introduction_run = RunOutput(
                run_id=str(uuid4()),
                session_id=session_id,
                agent_id=agent.id,
                agent_name=agent.name,
                user_id=user_id,
                content=agent.introduction,
                messages=[
                    Message(role=agent.model.assistant_message_role, content=agent.introduction)  # type: ignore
                ],
            )
            agent_session.upsert_run(introduction_run)

            # v3: session.runs is in-memory; persist the intro to the runs table
            # so a session reload picks it up (pre-3.0's save_session wrote the
            # entire runs blob, so this happened for free).
            if agent.db is not None and agent.team_id is None and agent.workflow_id is None:
                from agno.agent._session import asave_session, save_session
                from agno.agent._storage import aupsert_run, upsert_run

                if _init.has_async_db(agent):
                    await asave_session(agent, session=agent_session)
                    await aupsert_run(agent, run=introduction_run, session_id=session_id, user_id=user_id, run_index=0)
                else:
                    save_session(agent, session=agent_session)
                    upsert_run(agent, run=introduction_run, session_id=session_id, user_id=user_id, run_index=0)

    if agent.cache_session:
        agent._set_cached_session(agent_session)

    return agent_session


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def get_agent_data(agent: Agent) -> Dict[str, Any]:
    agent_data: Dict[str, Any] = {}
    if agent.name is not None:
        agent_data["name"] = agent.name
    if agent.id is not None:
        agent_data["agent_id"] = agent.id
    if agent.model is not None:
        agent_data["model"] = agent.model.to_dict()
    return agent_data


def _unresolvable_tool_name(entry: Any) -> Optional[str]:
    """The display name of a tools entry that cannot execute without intervention.

    A rebuilt Function with no entrypoint (and no client-side execution) lost
    its implementation and needs the registry - or a connected MCP toolkit -
    to supply one. A dict that is nothing but a name (and provenance) is a
    bare reference no registry can satisfy (rehydration needs a ``parameters``
    key), so it needs the component re-saved from code. Any other dict is the
    provider's to accept or reject and rides through untouched.
    """
    if isinstance(entry, Function):
        if entry.entrypoint is None and not entry.external_execution:
            return f"{entry.owning_toolkit}.{entry.name}" if entry.owning_toolkit else entry.name
        return None
    if isinstance(entry, dict) and entry.get("name") and set(entry.keys()) <= {"name", "description", "toolkit"}:
        # Positively a reference: nothing but a name (and provenance). Every
        # provider-native shape carries more - a type, a schema, parameters,
        # or a provider envelope - and rides through untouched.
        return str(entry["name"])
    return None


def to_dict(agent: Agent) -> Dict[str, Any]:
    """
    Convert the Agent to a dictionary.

    Returns:
        Dict[str, Any]: Dictionary representation of the agent configuration
    """
    from agno.agent._tools import parse_tools

    config: Dict[str, Any] = {}

    # --- Agent Settings ---
    if agent.model is not None:
        if isinstance(agent.model, Model):
            config["model"] = agent.model.to_dict()
        else:
            config["model"] = str(agent.model)
    if agent.name is not None:
        config["name"] = agent.name
    if agent.id is not None:
        config["id"] = agent.id

    # --- User settings ---
    if agent.user_id is not None:
        config["user_id"] = agent.user_id

    # --- Session settings ---
    if agent.session_id is not None:
        config["session_id"] = agent.session_id
    if agent.session_state is not None:
        config["session_state"] = agent.session_state
    if agent.add_session_state_to_context:
        config["add_session_state_to_context"] = agent.add_session_state_to_context
    if agent.enable_agentic_state:
        config["enable_agentic_state"] = agent.enable_agentic_state
    if agent.overwrite_db_session_state:
        config["overwrite_db_session_state"] = agent.overwrite_db_session_state
    if agent.cache_session:
        config["cache_session"] = agent.cache_session
    if agent.search_past_sessions:
        config["search_past_sessions"] = agent.search_past_sessions
    if agent.num_past_sessions_to_search is not None:
        config["num_past_sessions_to_search"] = agent.num_past_sessions_to_search
    if agent.num_past_session_runs_in_search is not None:
        config["num_past_session_runs_in_search"] = agent.num_past_session_runs_in_search
    if agent.enable_session_summaries:
        config["enable_session_summaries"] = agent.enable_session_summaries
    if agent.add_session_summary_to_context is not None:
        config["add_session_summary_to_context"] = agent.add_session_summary_to_context
    # TODO: implement session summary manager serialization
    # if agent.session_summary_manager is not None:
    #     config["session_summary_manager"] = agent.session_summary_manager.to_dict()

    # --- Dependencies ---
    if agent.dependencies is not None:
        config["dependencies"] = agent.dependencies
    if agent.add_dependencies_to_context:
        config["add_dependencies_to_context"] = agent.add_dependencies_to_context

    # --- Agentic Memory settings ---
    # Stored as a registry reference by id, like knowledge: the manager holds
    # a model and callables, so the config names it and the registry supplies
    # the live object on load. An auto-generated id is minted fresh every
    # process, so it can never resolve in a new one: writing it would poison
    # every future strict load. Only a stable, user-assigned id is referenced.
    if agent.memory_manager is not None:
        memory_manager_id = getattr(agent.memory_manager, "id", None)
        if memory_manager_id and not is_auto_generated_memory_manager_id(memory_manager_id):
            config["memory_manager"] = {"registry_id": memory_manager_id}
        elif agent.enable_agentic_memory or agent.update_memory_on_run:
            # The default manager initialize_agent builds; it rebuilds itself
            # from these flags on load, so there is nothing to reference.
            log_debug("Agent memory_manager has an auto-generated id; not saved, the default rebuilds on load.")
        else:
            log_warning(
                "Agent memory_manager has no stable id, so it cannot be referenced across processes and will "
                "not be saved. Give the manager an explicit id and register it in the registry to keep it."
            )
    if agent.enable_agentic_memory:
        config["enable_agentic_memory"] = agent.enable_agentic_memory
    if agent.update_memory_on_run:
        config["update_memory_on_run"] = agent.update_memory_on_run
    if agent.add_memories_to_context is not None:
        config["add_memories_to_context"] = agent.add_memories_to_context

    # --- Learning settings ---
    # A named machine is a registry resource: stored as a reference by name,
    # like knowledge, and resolved from the registry on load. Its config is
    # never inlined, so a stored component cannot carry learning the deployer
    # did not declare. An unnamed machine belongs to this component and is
    # inlined in full.
    if agent.learning is not None:
        learning_name = getattr(agent.learning, "name", None)
        if agent.learning is True:
            config["learning"] = True
        elif agent.learning is False:
            config["learning"] = False
        elif isinstance(learning_name, str) and learning_name:
            config["learning"] = {"name": learning_name}
        elif hasattr(agent.learning, "to_dict"):
            config["learning"] = agent.learning.to_dict()
        else:
            config["learning"] = True if agent.learning else False
    if not agent.add_learnings_to_context:  # default is True
        config["add_learnings_to_context"] = agent.add_learnings_to_context

    # --- Database settings ---
    if agent.db is not None and hasattr(agent.db, "to_dict"):
        config["db"] = agent.db.to_dict()

    # --- History settings ---
    if agent.add_history_to_context:
        config["add_history_to_context"] = agent.add_history_to_context
    if agent.num_history_runs is not None:
        config["num_history_runs"] = agent.num_history_runs
    if agent.num_history_messages is not None:
        config["num_history_messages"] = agent.num_history_messages
    if agent.max_tool_calls_from_history is not None:
        config["max_tool_calls_from_history"] = agent.max_tool_calls_from_history

    # --- Knowledge settings ---
    # Knowledge is a non-serializable object (it holds live db/vector_db connections),
    # so we store a reference by name and resolve it from the registry on load.
    if agent.knowledge is not None:
        knowledge_name = getattr(agent.knowledge, "name", None)
        if knowledge_name is not None:
            config["knowledge"] = {"name": knowledge_name}
        else:
            log_warning("Agent knowledge has no name; it cannot be referenced from the registry and will not be saved.")
    if agent.knowledge_filters is not None:
        config["knowledge_filters"] = agent.knowledge_filters
    if agent.enable_agentic_knowledge_filters:
        config["enable_agentic_knowledge_filters"] = agent.enable_agentic_knowledge_filters
    if agent.add_knowledge_to_context:
        config["add_knowledge_to_context"] = agent.add_knowledge_to_context
    if not agent.search_knowledge:
        config["search_knowledge"] = agent.search_knowledge
    if agent.add_search_knowledge_instructions:
        config["add_search_knowledge_instructions"] = agent.add_search_knowledge_instructions
    # Skip knowledge_retriever as it's a callable
    if agent.references_format != "json":
        config["references_format"] = agent.references_format

    # --- Tools ---
    # Serialize tools to their dictionary representations (skip callable factories)
    _tools: List[Union[Function, dict]] = []
    # Which toolkit each flattened function came from, so rehydration can
    # re-bind same-named functions to the right toolkit (see
    # Registry.rehydrate_function). Mirrors the parse_tools walk: tools are
    # processed in declaration order and the first one to claim a name wins.
    _owning_toolkit: Dict[str, str] = {}
    if agent.model is not None and agent.tools and isinstance(agent.tools, list):
        _tools = parse_tools(
            agent,
            model=agent.model,
            tools=agent.tools,
        )
        _claimed_names: Set[str] = set()
        for _tool in agent.tools:
            if isinstance(_tool, Toolkit):
                # get_functions() is what parse_tools serializes. Names are claimed
                # by Function.name, which is what the serialized dict carries.
                for _func in _tool.get_functions().values():
                    if _func.name in _claimed_names:
                        continue
                    _claimed_names.add(_func.name)
                    if isinstance(_tool.name, str) and _tool.name:
                        _owning_toolkit[_func.name] = _tool.name
            elif isinstance(_tool, Function):
                if _tool.name not in _claimed_names:
                    _claimed_names.add(_tool.name)
                    if _tool.owning_toolkit:
                        _owning_toolkit[_tool.name] = _tool.owning_toolkit
            elif callable(_tool) and getattr(_tool, "__name__", None) is not None:
                _claimed_names.add(_tool.__name__)
    if _tools:
        serialized_tools = []
        for tool in _tools:
            try:
                if isinstance(tool, Function):
                    tool_dict = tool.to_dict()
                    _toolkit_name = _owning_toolkit.get(tool.name)
                    if _toolkit_name is not None:
                        tool_dict["toolkit"] = _toolkit_name
                    serialized_tools.append(tool_dict)
                else:
                    serialized_tools.append(tool)
            except Exception as e:
                # Skip tools that can't be serialized
                log_warning(f"Could not serialize tool {tool}: {str(e)}")
        if serialized_tools:
            config["tools"] = serialized_tools

    if agent.tool_call_limit is not None:
        config["tool_call_limit"] = agent.tool_call_limit
    if agent.tool_choice is not None:
        config["tool_choice"] = agent.tool_choice

    # --- Reasoning settings ---
    if agent.reasoning_model is not None:
        if isinstance(agent.reasoning_model, Model):
            config["reasoning_model"] = agent.reasoning_model.to_dict()
        else:
            config["reasoning_model"] = str(agent.reasoning_model)
    # Skip reasoning_agent to avoid circular serialization

    # --- Default tools settings ---
    if agent.read_chat_history:
        config["read_chat_history"] = agent.read_chat_history
    if agent.update_knowledge:
        config["update_knowledge"] = agent.update_knowledge
    if agent.read_tool_call_history:
        config["read_tool_call_history"] = agent.read_tool_call_history
    if not agent.send_media_to_model:
        config["send_media_to_model"] = agent.send_media_to_model
    if not agent.store_media:
        config["store_media"] = agent.store_media
    if not agent.store_tool_messages:
        config["store_tool_messages"] = agent.store_tool_messages
    if agent.store_history_messages:
        config["store_history_messages"] = agent.store_history_messages

    # --- System message settings ---
    # Skip system_message if it's a callable or Message object
    # TODO: Support Message objects
    if agent.system_message is not None and isinstance(agent.system_message, str):
        config["system_message"] = agent.system_message
    if agent.system_message_role != "system":
        config["system_message_role"] = agent.system_message_role
    if not agent.build_context:
        config["build_context"] = agent.build_context

    # --- Context building settings ---
    if agent.description is not None:
        config["description"] = agent.description
    # Handle instructions (can be str, list, or callable)
    if agent.instructions is not None:
        if isinstance(agent.instructions, str):
            config["instructions"] = agent.instructions
        elif isinstance(agent.instructions, list):
            config["instructions"] = agent.instructions
        # Skip if callable
    if agent.expected_output is not None:
        config["expected_output"] = agent.expected_output
    if agent.additional_context is not None:
        config["additional_context"] = agent.additional_context
    if agent.markdown:
        config["markdown"] = agent.markdown
    if agent.add_name_to_context:
        config["add_name_to_context"] = agent.add_name_to_context
    if agent.add_datetime_to_context:
        config["add_datetime_to_context"] = agent.add_datetime_to_context
    if agent.add_location_to_context:
        config["add_location_to_context"] = agent.add_location_to_context
    if agent.timezone_identifier is not None:
        config["timezone_identifier"] = agent.timezone_identifier
    if agent.datetime_format is not None:
        config["datetime_format"] = agent.datetime_format
    if not agent.resolve_in_context:
        config["resolve_in_context"] = agent.resolve_in_context

    # --- Additional input ---
    # Skip additional_input as it may contain complex Message objects
    # TODO: Support Message objects

    # --- User message settings ---
    if agent.user_message_role != "user":
        config["user_message_role"] = agent.user_message_role
    if not agent.build_user_context:
        config["build_user_context"] = agent.build_user_context

    # --- Response settings ---
    if agent.retries > 0:
        config["retries"] = agent.retries
    if agent.delay_between_retries != 1:
        config["delay_between_retries"] = agent.delay_between_retries
    if agent.exponential_backoff:
        config["exponential_backoff"] = agent.exponential_backoff

    # --- Schema settings ---
    if agent.input_schema is not None:
        if isinstance(agent.input_schema, type) and issubclass(agent.input_schema, BaseModel):
            config["input_schema"] = agent.input_schema.__name__
        elif isinstance(agent.input_schema, dict):
            config["input_schema"] = agent.input_schema
    if agent.output_schema is not None:
        if isinstance(agent.output_schema, type) and issubclass(agent.output_schema, BaseModel):
            config["output_schema"] = agent.output_schema.__name__
        elif isinstance(agent.output_schema, dict):
            config["output_schema"] = agent.output_schema

    # --- Parser and output settings ---
    if agent.parser_model is not None:
        if isinstance(agent.parser_model, Model):
            config["parser_model"] = agent.parser_model.to_dict()
        else:
            config["parser_model"] = str(agent.parser_model)
    if agent.parser_model_prompt is not None:
        config["parser_model_prompt"] = agent.parser_model_prompt
    if agent.output_model is not None:
        if isinstance(agent.output_model, Model):
            config["output_model"] = agent.output_model.to_dict()
        else:
            config["output_model"] = str(agent.output_model)
    if agent.output_model_prompt is not None:
        config["output_model_prompt"] = agent.output_model_prompt
    if not agent.parse_response:
        config["parse_response"] = agent.parse_response
    if agent.structured_outputs is not None:
        config["structured_outputs"] = agent.structured_outputs
    if agent.use_json_mode:
        config["use_json_mode"] = agent.use_json_mode
    if agent.save_response_to_file is not None:
        config["save_response_to_file"] = agent.save_response_to_file

    # --- Streaming settings ---
    if agent.stream is not None:
        config["stream"] = agent.stream
    if agent.stream_events is not None:
        config["stream_events"] = agent.stream_events
    if agent.store_events:
        config["store_events"] = agent.store_events
    # Skip events_to_skip as it contains RunEvent enums

    # --- Role settings ---
    if agent.role is not None:
        config["role"] = agent.role
    # --- Team and workflow settings ---
    if agent.team_id is not None:
        config["team_id"] = agent.team_id
    if agent.workflow_id is not None:
        config["workflow_id"] = agent.workflow_id

    # --- Metadata ---
    if agent.metadata is not None:
        config["metadata"] = agent.metadata

    # --- Context compression settings ---
    if agent.compress_tool_results:
        config["compress_tool_results"] = agent.compress_tool_results

    # --- Result offloading settings ---
    if agent.offload_tool_results is not None:
        config["offload_tool_results"] = _offload_to_config(agent.offload_tool_results)
    # TODO: implement compression manager serialization
    # if agent.compression_manager is not None:
    #     config["compression_manager"] = agent.compression_manager.to_dict()

    # --- Callable factory settings ---
    if not agent.cache_callables:
        config["cache_callables"] = agent.cache_callables

    # --- Debug and telemetry settings ---
    if agent.debug_mode:
        config["debug_mode"] = agent.debug_mode
    if agent.debug_level != 1:
        config["debug_level"] = agent.debug_level
    if not agent.telemetry:
        config["telemetry"] = agent.telemetry

    return config


def from_dict(
    cls: Type[Agent], data: Dict[str, Any], registry: Optional[Registry] = None, strict: bool = False
) -> Agent:
    """
    Create an agent from a dictionary.

    Args:
        cls: The Agent class (or subclass) to instantiate.
        data: Dictionary containing agent configuration
        registry: Optional registry for rehydrating tools and schemas
        strict: If True, unresolvable registry references (tools,
            schemas, knowledge) raise ComponentRehydrationError instead of
            being silently dropped; an unresolvable serialized db config warns
            and falls back to the caller's db in both modes. Pass False to
            reconstruct as much as possible, e.g. for listings that must show
            degraded components.

    Returns:
        Agent: Reconstructed agent instance

    Raises:
        ComponentRehydrationError: If strict and a registry reference cannot be resolved.
    """
    from agno.models.utils import resolve_model

    component_label = f"Agent '{data.get('id') or data.get('name') or '<unknown>'}'"

    config = data.copy()

    # --- Handle Model reconstruction ---
    if "model" in config:
        config["model"] = resolve_model(config["model"], registry)

    # --- Handle reasoning_model reconstruction ---
    if config.get("reasoning_model") is not None:
        config["reasoning_model"] = resolve_model(config["reasoning_model"], registry)

    # --- Handle parser_model reconstruction ---
    # TODO: implement parser model deserialization
    # if "parser_model" in config:
    #     model_data = config["parser_model"]
    #     if isinstance(model_data, dict) and "id" in model_data:
    #         config["parser_model"] = get_model(f"{model_data['provider']}:{model_data['id']}")
    #     elif isinstance(model_data, str):
    #         config["parser_model"] = get_model(model_data)

    # --- Handle output_model reconstruction ---
    # TODO: implement output model deserialization
    # if "output_model" in config:
    #     model_data = config["output_model"]
    #     if isinstance(model_data, dict) and "id" in model_data:
    #         config["output_model"] = get_model(f"{model_data['provider']}:{model_data['id']}")
    #     elif isinstance(model_data, str):
    #         config["output_model"] = get_model(model_data)

    # --- Handle tools reconstruction ---
    if "tools" in config and config["tools"]:
        if registry:
            rehydrated_tools = registry.rehydrate_functions(config["tools"], strict=strict)
            unresolved_tools = [
                name for entry in rehydrated_tools if (name := _unresolvable_tool_name(entry)) is not None
            ]
            if unresolved_tools and strict:
                raise ComponentRehydrationError(
                    f"{component_label} references tools not resolvable from the registry: "
                    f"{unresolved_tools}. Add missing tools to the registry (and connect MCP "
                    "toolkits before loading); a bare name-only reference cannot be resolved from "
                    "a registry and needs the component re-saved from code. Or pass strict=False."
                )
            config["tools"] = rehydrated_tools
        elif strict:
            # Provider-run dicts and external-execution tools need no registry;
            # an empty one gives them the same treatment a real one would.
            rehydrated_tools = Registry().rehydrate_functions(config["tools"], strict=True)
            unresolved_tools = [
                name for entry in rehydrated_tools if (name := _unresolvable_tool_name(entry)) is not None
            ]
            if unresolved_tools:
                raise ComponentRehydrationError(
                    f"{component_label} references tools that need a registry to rehydrate: "
                    f"{unresolved_tools}. Provide a registry, or pass strict=False to load the "
                    "component without them."
                )
            config["tools"] = rehydrated_tools
        else:
            rehydrated_tools = Registry().rehydrate_functions(config["tools"])
            unresolved_tools = [
                name for entry in rehydrated_tools if (name := _unresolvable_tool_name(entry)) is not None
            ]
            if unresolved_tools:
                log_warning(f"No registry provided; these tools cannot execute: {unresolved_tools}")
            config["tools"] = rehydrated_tools

    # --- Handle DB reconstruction ---
    if "db" in config and isinstance(config["db"], dict):
        resolved = resolve_db_from_config(config["db"], registry=registry)
        if resolved is not None:
            config["db"] = resolved
        else:
            # Only postgres, sqlite and clickhouse serialize a type; on other
            # backends the caller's own db is the fallback, in both modes.
            log_warning(f"{component_label} has a serialized db config that could not be resolved.")
            del config["db"]

    # --- Handle Schema reconstruction ---
    if "input_schema" in config and isinstance(config["input_schema"], str):
        schema_cls = registry.get_schema(config["input_schema"]) if registry else None
        if schema_cls:
            config["input_schema"] = schema_cls
        elif strict:
            raise ComponentRehydrationError(
                f"{component_label} references input schema '{config['input_schema']}' which was not "
                "found in the registry. Register the schema, or pass strict=False to load the "
                "component without it."
            )
        else:
            log_warning(f"Input schema {config['input_schema']} not found in registry, skipping.")
            del config["input_schema"]

    if "output_schema" in config and isinstance(config["output_schema"], str):
        schema_cls = registry.get_schema(config["output_schema"]) if registry else None
        if schema_cls:
            config["output_schema"] = schema_cls
        elif strict:
            raise ComponentRehydrationError(
                f"{component_label} references output schema '{config['output_schema']}' which was not "
                "found in the registry. Register the schema, or pass strict=False to load the "
                "component without it."
            )
        else:
            log_warning(f"Output schema {config['output_schema']} not found in registry, skipping.")
            del config["output_schema"]

    # --- Handle MemoryManager reconstruction ---
    resolve_memory_manager_reference(config, registry, strict, component_label)

    # --- Handle SessionSummaryManager reconstruction ---
    # TODO: implement session summary manager deserialization
    # if "session_summary_manager" in config and isinstance(config["session_summary_manager"], dict):
    #     from agno.session import SessionSummaryManager
    #     config["session_summary_manager"] = SessionSummaryManager.from_dict(config["session_summary_manager"])

    # --- Handle Knowledge reconstruction ---
    # Knowledge is stored as a reference by name and resolved from the registry,
    # since it holds live db/vector_db connections that cannot be serialized.
    if "knowledge" in config and isinstance(config["knowledge"], dict):
        knowledge_name = config["knowledge"].get("name")
        if strict and registry and knowledge_name and registry.knowledge_name_is_ambiguous(knowledge_name):
            raise ComponentRehydrationError(
                f"{component_label} references knowledge '{knowledge_name}', but two distinct "
                "knowledge instances share that name, so the reference could bind the wrong "
                "store. Give the instances distinct names."
            )
        resolved_knowledge = registry.get_knowledge(knowledge_name) if (registry and knowledge_name) else None
        if resolved_knowledge is not None:
            config["knowledge"] = resolved_knowledge
        elif strict:
            raise ComponentRehydrationError(
                f"{component_label} references knowledge '{knowledge_name}' which was not found in "
                "the registry. Register the knowledge, or pass strict=False to load the component "
                "without it."
            )
        else:
            log_warning(f"Knowledge '{knowledge_name}' not found in registry, skipping.")
            del config["knowledge"]

    # --- Handle CompressionManager reconstruction ---
    # TODO: implement compression manager deserialization
    # if "compression_manager" in config and isinstance(config["compression_manager"], dict):
    #     from agno.compression.manager import CompressionManager
    #     config["compression_manager"] = CompressionManager.from_dict(config["compression_manager"])

    # --- Handle Learning reconstruction ---
    # A named machine is stored as a reference and resolved from the registry;
    # any other dict is an inline machine config and is rebuilt here.
    resolve_learning_reference(config, registry, strict, component_label)
    if "learning" in config and isinstance(config["learning"], dict):
        from agno.learn.machine import LearningMachine

        # An inline machine belongs to this component: a name on it is dropped
        # so the rebuilt machine keeps round-tripping inline instead of being
        # re-saved as a reference to a machine no registry declares.
        inline = {key: value for key, value in config["learning"].items() if key != "name"}
        config["learning"] = LearningMachine.from_dict(inline)

    # Remove keys that aren't constructor parameters
    config.pop("team_id", None)
    config.pop("workflow_id", None)

    return cls(
        # --- Agent settings ---
        model=config.get("model"),
        name=config.get("name"),
        id=config.get("id"),
        # --- User settings ---
        user_id=config.get("user_id"),
        # --- Session settings ---
        session_id=config.get("session_id"),
        session_state=config.get("session_state"),
        add_session_state_to_context=config.get("add_session_state_to_context", False),
        enable_agentic_state=config.get("enable_agentic_state", False),
        overwrite_db_session_state=config.get("overwrite_db_session_state", False),
        cache_session=config.get("cache_session", False),
        search_past_sessions=config.get("search_past_sessions", False),
        num_past_sessions_to_search=config.get("num_past_sessions_to_search"),
        num_past_session_runs_in_search=config.get("num_past_session_runs_in_search"),
        enable_session_summaries=config.get("enable_session_summaries", False),
        add_session_summary_to_context=config.get("add_session_summary_to_context"),
        # session_summary_manager=config.get("session_summary_manager"),  # TODO
        # --- Dependencies ---
        dependencies=config.get("dependencies"),
        add_dependencies_to_context=config.get("add_dependencies_to_context", False),
        # --- Agentic Memory settings ---
        memory_manager=config.get("memory_manager"),
        enable_agentic_memory=config.get("enable_agentic_memory", False),
        update_memory_on_run=config.get("update_memory_on_run", False),
        add_memories_to_context=config.get("add_memories_to_context"),
        # --- Learning settings ---
        learning=config.get("learning"),
        add_learnings_to_context=config.get("add_learnings_to_context", True),
        # --- Database settings ---
        db=config.get("db"),
        # --- History settings ---
        add_history_to_context=config.get("add_history_to_context", False),
        num_history_runs=config.get("num_history_runs"),
        num_history_messages=config.get("num_history_messages"),
        max_tool_calls_from_history=config.get("max_tool_calls_from_history"),
        # --- Knowledge settings ---
        knowledge=config.get("knowledge"),
        knowledge_filters=config.get("knowledge_filters"),
        enable_agentic_knowledge_filters=config.get("enable_agentic_knowledge_filters", False),
        add_knowledge_to_context=config.get("add_knowledge_to_context", False),
        references_format=config.get("references_format", "json"),
        # --- Tools ---
        tools=config.get("tools"),
        tool_call_limit=config.get("tool_call_limit"),
        tool_choice=config.get("tool_choice"),
        # --- Reasoning settings ---
        reasoning_model=config.get("reasoning_model"),
        # --- Default tools settings ---
        read_chat_history=config.get("read_chat_history", False),
        search_knowledge=config.get("search_knowledge", True),
        add_search_knowledge_instructions=config.get("add_search_knowledge_instructions", True),
        update_knowledge=config.get("update_knowledge", False),
        read_tool_call_history=config.get("read_tool_call_history", False),
        send_media_to_model=config.get("send_media_to_model", True),
        store_media=config.get("store_media", True),
        store_tool_messages=config.get("store_tool_messages", True),
        store_history_messages=config.get("store_history_messages", False),
        # --- System message settings ---
        system_message=config.get("system_message"),
        system_message_role=config.get("system_message_role", "system"),
        build_context=config.get("build_context", True),
        # --- Context building settings ---
        description=config.get("description"),
        instructions=config.get("instructions"),
        expected_output=config.get("expected_output"),
        additional_context=config.get("additional_context"),
        markdown=config.get("markdown", False),
        add_name_to_context=config.get("add_name_to_context", False),
        add_datetime_to_context=config.get("add_datetime_to_context", False),
        add_location_to_context=config.get("add_location_to_context", False),
        datetime_format=config.get("datetime_format"),
        timezone_identifier=config.get("timezone_identifier"),
        resolve_in_context=config.get("resolve_in_context", True),
        # --- User message settings ---
        user_message_role=config.get("user_message_role", "user"),
        build_user_context=config.get("build_user_context", True),
        # --- Response settings ---
        retries=config.get("retries", 0),
        delay_between_retries=config.get("delay_between_retries", 1),
        exponential_backoff=config.get("exponential_backoff", False),
        # --- Schema settings ---
        input_schema=config.get("input_schema"),
        output_schema=config.get("output_schema"),
        # --- Parser and output settings ---
        # parser_model=config.get("parser_model"),  # TODO
        parser_model_prompt=config.get("parser_model_prompt"),
        # output_model=config.get("output_model"),  # TODO
        output_model_prompt=config.get("output_model_prompt"),
        parse_response=config.get("parse_response", True),
        structured_outputs=config.get("structured_outputs"),
        use_json_mode=config.get("use_json_mode", False),
        save_response_to_file=config.get("save_response_to_file"),
        # --- Streaming settings ---
        stream=config.get("stream"),
        stream_events=config.get("stream_events"),
        store_events=config.get("store_events", False),
        role=config.get("role"),
        # --- Metadata ---
        metadata=strip_reserved_run_metadata(config.get("metadata")),
        # --- Compression settings ---
        compress_tool_results=config.get("compress_tool_results", False),
        # compression_manager=config.get("compression_manager"),  # TODO
        # --- Result offloading settings ---
        offload_tool_results=_offload_from_config(config.get("offload_tool_results")),
        # --- Debug and telemetry settings ---
        debug_mode=config.get("debug_mode", False),
        debug_level=config.get("debug_level", 1),
        telemetry=config.get("telemetry", True),
    )


# ---------------------------------------------------------------------------
# Component persistence
# ---------------------------------------------------------------------------


def save(
    agent: Agent,
    *,
    db: Optional[BaseDb] = None,
    stage: str = "published",
    label: Optional[str] = None,
    notes: Optional[str] = None,
) -> Optional[int]:
    """
    Save the agent component and config.

    Args:
        agent: The Agent instance.
        db: The database to save the component and config to.
        stage: The stage of the component. Defaults to "published".
        label: The label of the component.
        notes: The notes of the component.

    Returns:
        Optional[int]: The version number of the saved config.
    """
    db_ = db or agent.db
    if not db_:
        raise ValueError("Db not initialized or provided")
    if not isinstance(db_, BaseDb):
        raise ValueError("Async databases not yet supported for save(). Use a sync database.")

    if agent.id is None:
        agent.id = generate_id_from_name(agent.name)

    try:
        # Create or update component
        db_.upsert_component(
            component_id=agent.id,
            component_type=ComponentType.AGENT,
            name=getattr(agent, "name", agent.id),
            description=getattr(agent, "description", None),
            metadata=getattr(agent, "metadata", None),
        )

        # Create or update config
        config = db_.upsert_config(
            component_id=agent.id,
            config=to_dict(agent),
            label=label,
            stage=stage,
            notes=notes,
        )

        return config.get("version")

    except Exception as e:
        log_error(f"Error saving Agent to database: {str(e)}")
        raise


def load(
    cls: Type[Agent],
    id: str,
    *,
    db: BaseDb,
    registry: Optional[Registry] = None,
    label: Optional[str] = None,
    version: Optional[int] = None,
    strict: bool = False,
    published_only: bool = False,
) -> Optional[Agent]:
    """
    Load an agent by id.

    Args:
        cls: The Agent class (or subclass) to instantiate.
        id: The id of the agent to load.
        db: The database to load the agent from.
        registry: Optional registry for rehydrating tools and schemas.
        label: The label of the agent to load.
        version: The version of the agent to load.
        strict: If True, unresolvable registry references raise
            ComponentRehydrationError instead of being silently dropped.

    Returns:
        The agent loaded from the database or None if not found.
    """

    if published_only and version is None and label is None:
        # Dispatch semantics on demand: resolve strictly through the live
        # pointer instead of the current-or-latest-draft read fallback.
        component_row = db.get_component(component_id=id)
        current_version = component_row.get("current_version") if isinstance(component_row, dict) else None
        if current_version is None:
            return None
        version = current_version

    data = db.get_config(component_id=id, label=label, version=version)
    if data is None:
        return None

    config = data.get("config")
    if config is None:
        return None

    agent = cls.from_dict(config, registry=registry, strict=strict)
    agent.id = id
    # Only fall back to the caller-provided db if the config didn't
    # reconstruct one. Otherwise we'd clobber any custom table names
    # (session_table, memory_table, ...) that were serialized with the agent.
    if agent.db is None:
        if strict:
            require_db_fallback_matches(config, db, "agent", id)
        agent.db = db

    return agent


def delete(
    agent: Agent,
    *,
    db: Optional[BaseDb] = None,
    hard_delete: bool = False,
    require_no_dependents: bool = True,
) -> bool:
    """
    Delete the agent component.

    Args:
        agent: The Agent instance.
        db: The database to delete the component from.
        hard_delete: Whether to hard delete the component.
        require_no_dependents: Refuse when another component pins this one.
            The default protects a composition from losing a member it cannot
            rebuild; pass False to delete anyway and leave those parents
            pointing at nothing.

    Returns:
        True if the component was deleted, False if there was nothing to delete.

    Raises:
        ComponentDependencyError: If another component pins this one and
            require_no_dependents is True.
    """
    db_ = db or agent.db
    if not db_:
        raise ValueError("Db not initialized or provided")
    if not isinstance(db_, BaseDb):
        raise ValueError("Async databases not yet supported for delete(). Use a sync database.")
    if agent.id is None:
        raise ValueError("Cannot delete agent without an id")

    return db_.delete_component(
        component_id=agent.id, hard_delete=hard_delete, require_no_dependents=require_no_dependents
    )
