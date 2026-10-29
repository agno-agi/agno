"""Store external agent adapters as component configs and rebuild them.

A stored config carries the adapter's own settings as JSON, plus references
to the objects that live outside it: the db, the sandbox and a Pydantic
output schema. The registry supplies those on load, as it does for Agent.
The ``sdk`` key names the adapter, so a loader can tell a stored ClaudeAgent
from a stored Agent before building either.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import MISSING, fields
from enum import Enum
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Type

from pydantic import BaseModel

from agno.db.base import BaseDb, ComponentType
from agno.db.utils import resolve_db_from_config
from agno.exceptions import ComponentRehydrationError
from agno.registry._reserved import RESERVED_MANAGER_IDS, _reserved_manager_id_message
from agno.run.agent import RunEvent
from agno.utils.db_fallback import require_db_fallback_matches
from agno.utils.log import log_error, log_warning
from agno.utils.string import generate_id_from_name

if TYPE_CHECKING:
    from agno.agents.base import BaseExternalAgent
    from agno.registry import Registry

# The adapters a stored config can name, keyed by the sdk value they write.
STORABLE_ADAPTERS: Dict[str, Tuple[str, str]] = {
    "claude-agent-sdk": ("agno.agents.claude", "ClaudeAgent"),
    "codex": ("agno.agents.codex", "CodexAgent"),
}

# What __post_init__ sets when events_to_skip is left at None; not stored.
_DEFAULT_EVENTS_TO_SKIP: List[RunEvent] = [RunEvent.run_content]


def stored_agent_sdk(db: BaseDb, component_id: str) -> Optional[Tuple[bool, Optional[str]]]:
    """(exists, sdk) for the component's current config; None when there is no config."""
    try:
        row = db.get_config(component_id=component_id)
    except NotImplementedError:
        return None
    config = row.get("config") if isinstance(row, dict) else None
    if not isinstance(config, dict):
        return None
    sdk = config.get("sdk")
    return True, sdk if isinstance(sdk, str) else None


def require_same_agent_kind(db: BaseDb, component_id: str, sdk: Optional[str]) -> None:
    """Refuse a save that would change what a stored agent loads as.

    Agent and the adapters share one catalog, keyed by id. Saving an Agent over
    a stored ClaudeAgent (or the reverse) would silently switch runtimes and
    drop the other kind's settings on the next load.
    """
    stored = stored_agent_sdk(db, component_id)
    if stored is None:
        return
    _, stored_sdk = stored
    if stored_sdk == sdk:
        return

    def describe(value: Optional[str]) -> str:
        return "an Agent" if value is None else f"a {value!r} external agent"

    raise ValueError(
        f"Component {component_id!r} is stored as {describe(stored_sdk)}; saving {describe(sdk)} under the same "
        "id would change what it loads as. Use another id, or delete the component first."
    )


def require_host_execution_allowed(agent: "BaseExternalAgent", registry: Optional["Registry"]) -> None:
    """Refuse to serve a stored adapter on this host unless the deployer opted in.

    A sandboxed adapter runs in a registered sandbox the deployer declared. One
    without a sandbox runs on the AgentOS host with the working directory, MCP
    server commands, plugins and permission mode its stored config names.
    """
    if agent.sandbox is not None:
        return
    if registry is not None and registry.allow_host_external_agents:
        return
    raise ComponentRehydrationError(
        f"Agent '{agent.get_id()}' is a stored {agent.sdk!r} external agent without a sandbox, which this "
        "AgentOS does not run on its host. Give it a registered sandbox, or opt in with "
        "Registry(allow_host_external_agents=True)."
    )


def is_external_agent_config(config: Any) -> bool:
    """Whether a stored agent config describes an external adapter rather than an Agent."""
    return isinstance(config, dict) and isinstance(config.get("sdk"), str)


def external_agent_class(sdk: str) -> Type["BaseExternalAgent"]:
    """The adapter class a stored config's sdk value names."""
    target = STORABLE_ADAPTERS.get(sdk)
    if target is None:
        raise ComponentRehydrationError(
            f"No external agent adapter stores configs with sdk {sdk!r}; "
            f"storable adapters are: {', '.join(sorted(STORABLE_ADAPTERS))}"
        )
    module_name, class_name = target
    return getattr(import_module(module_name), class_name)


def _is_default(item: Any, value: Any) -> bool:
    if item.default is not MISSING:
        return value == item.default
    if item.default_factory is not MISSING:
        return value == item.default_factory()
    return False


def _plain(value: Any) -> Any:
    """Paths, enums and tuples in their JSON spelling; everything else as is."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _jsonable(agent: "BaseExternalAgent", name: str, value: Any) -> Any:
    plain = _plain(value)
    try:
        return json.loads(json.dumps(plain, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"{type(agent).__name__}.{name} cannot be stored as a component config: it holds a value that "
            f"is not JSON ({error}). Keep live objects out of it, or register the agent in code instead."
        ) from error


def to_dict(agent: "BaseExternalAgent") -> Dict[str, Any]:
    """The adapter's non-default settings as a component config.

    The db, the sandbox and a Pydantic output schema are stored as references
    the registry resolves on load. A field the adapter marks unstorable is
    refused when set: those hold callables, host paths or credentials, and a
    config that silently dropped them would rebuild a different agent.
    """
    cls = type(agent)
    if not cls._storable:
        raise NotImplementedError(f"{cls.__name__} cannot be stored as a component config")
    config: Dict[str, Any] = {"sdk": agent.sdk}
    for item in fields(agent):
        if not item.init:
            continue
        name = item.name
        value = getattr(agent, name)
        if name in cls._unstorable_fields:
            if value is None or _is_default(item, value):
                continue
            raise ValueError(
                f"{cls.__name__}.{name} cannot be stored as a component config: {cls._unstorable_fields[name]}"
            )
        if name == "db":
            if value is not None and hasattr(value, "to_dict"):
                config["db"] = value.to_dict()
            continue
        if name == "sandbox":
            if value is not None:
                sandbox_id = getattr(value, "id", None)
                if not isinstance(sandbox_id, str) or not sandbox_id:
                    raise ValueError(
                        f"{cls.__name__}.sandbox has no id, so a stored config cannot refer to it. "
                        "Give the sandbox id= and register it in the registry."
                    )
                config["sandbox"] = {"id": sandbox_id}
            continue
        if name == "repository":
            if value is not None:
                config["repository"] = {"url": value.url, "branch": value.branch}
            continue
        if name == "output_schema":
            if isinstance(value, dict):
                config["output_schema"] = _jsonable(agent, name, value)
            elif isinstance(value, type) and issubclass(value, BaseModel):
                config["output_schema"] = value.__name__
            continue
        if name == "events_to_skip":
            if value is not None and list(value) != _DEFAULT_EVENTS_TO_SKIP:
                config["events_to_skip"] = [_plain(event) for event in value]
            continue
        if _is_default(item, value):
            continue
        config[cls._stored_as.get(name, name)] = _jsonable(agent, name, value)
    return config


def from_dict(
    cls: Type["BaseExternalAgent"],
    data: Dict[str, Any],
    registry: Optional["Registry"] = None,
    strict: bool = False,
) -> "BaseExternalAgent":
    """Rebuild an adapter from a stored config.

    Called on the base class, the config's sdk value picks the adapter; called
    on an adapter, the config must be one of its own. Strict loads refuse a
    reference the registry cannot resolve and a setting the adapter does not
    accept; lenient loads drop them with a warning so listings can still show
    the component.
    """
    from agno.agents.base import BaseExternalAgent

    if not isinstance(data, dict):
        raise ComponentRehydrationError("An external agent config must be a JSON object")
    config = dict(data)
    sdk = config.pop("sdk", None)
    target: Type[BaseExternalAgent]
    if cls is BaseExternalAgent or not cls._storable:
        if not isinstance(sdk, str):
            raise ComponentRehydrationError("An external agent config must name its adapter under 'sdk'")
        target = external_agent_class(sdk)
    else:
        target = cls
        if sdk is None:
            # Agent and the adapters share one catalog; a config without an sdk is an
            # Agent's, and building an adapter from it would drop that agent's settings.
            raise ComponentRehydrationError(
                f"The config carries no sdk, so it is stored for an Agent, not for {target.__name__}; "
                "load it with Agent.load or get_agent_by_id"
            )
        if sdk != target._sdk_name:
            raise ComponentRehydrationError(
                f"The config is stored for sdk {sdk!r}, not for {target.__name__} ({target._sdk_name!r})"
            )
    label = f"{target.__name__} '{config.get('id') or config.get('name') or '<unknown>'}'"

    if "db" in config:
        db_config = config.pop("db")
        if db_config is not None:
            resolved_db = resolve_db_from_config(db_config, registry=registry) if isinstance(db_config, dict) else None
            if resolved_db is not None:
                config["db"] = resolved_db
            else:
                # Only postgres, sqlite and clickhouse serialize a type; on other
                # backends the caller's own db is the fallback, in both modes.
                log_warning(f"{label} has a serialized db config that could not be resolved.")

    sandbox_dropped = False
    if "sandbox" in config:
        reference = config.pop("sandbox")
        if reference is not None:
            sandbox_id = reference.get("id") if isinstance(reference, dict) else None
            sandbox = registry.get_sandbox(sandbox_id) if registry is not None and isinstance(sandbox_id, str) else None
            if sandbox is not None:
                config["sandbox"] = sandbox
            elif strict:
                raise ComponentRehydrationError(
                    f"{label} references sandbox {sandbox_id!r} which was not found in the registry. "
                    "Register the sandbox (give it id= and pass it in Registry(sandboxes=[...]), or serve a "
                    "code-defined agent that uses it), or pass strict=False to load the component without it."
                )
            else:
                log_warning(f"Sandbox {sandbox_id!r} not found in registry, loading {label} without it.")
                sandbox_dropped = True

    if "repository" in config:
        repository = config.pop("repository")
        if repository is not None and sandbox_dropped:
            log_warning(f"{label} repository needs its sandbox, loading without it.")
        elif repository is not None:
            from agno.sandbox.repository import Repository

            if not isinstance(repository, dict):
                raise ComponentRehydrationError(f"{label} repository must be an object with url and branch")
            try:
                config["repository"] = Repository(**repository)
            except (TypeError, ValueError) as error:
                raise ComponentRehydrationError(f"{label} repository is invalid: {error}") from error

    if isinstance(config.get("output_schema"), str):
        schema_name = config["output_schema"]
        schema_cls = registry.get_schema(schema_name) if registry is not None else None
        if schema_cls is not None:
            config["output_schema"] = schema_cls
        elif strict:
            raise ComponentRehydrationError(
                f"{label} references output schema '{schema_name}' which was not found in the registry. "
                "Register the schema, or pass strict=False to load the component without it."
            )
        else:
            log_warning(f"Output schema {schema_name} not found in registry, skipping.")
            del config["output_schema"]

    if config.get("events_to_skip") is not None:
        try:
            config["events_to_skip"] = [RunEvent(value) for value in config["events_to_skip"]]
        except (TypeError, ValueError) as error:
            raise ComponentRehydrationError(f"{label} events_to_skip names an unknown event: {error}") from error

    accepted = {item.name for item in fields(target) if item.init}
    unknown = sorted(key for key in config if key not in accepted)
    if unknown:
        if strict:
            raise ComponentRehydrationError(
                f"{label} config carries settings {target.__name__} does not accept: {unknown}. "
                "Re-save the component, or pass strict=False to load it without them."
            )
        log_warning(f"{label} config carries settings {target.__name__} does not accept, skipping: {unknown}")
        for key in unknown:
            del config[key]

    try:
        return target(**config)
    except (TypeError, ValueError) as error:
        raise ComponentRehydrationError(f"{label} could not be rebuilt from its config: {error}") from error


def bind_loaded_agent(
    agent: "BaseExternalAgent",
    id: str,
    db: BaseDb,
    config: Dict[str, Any],
    strict: bool,
) -> "BaseExternalAgent":
    """Give a rebuilt adapter its component id and the caller's db where the config carried none.

    A sandboxed adapter validates its db at construction, which the config may
    not have carried, so the check runs again once the fallback is in place.
    """
    agent.id = id
    if agent.db is None:
        if strict:
            require_db_fallback_matches(config, db, "agent", id)
        agent.db = db
    if agent.sandbox is not None and strict:
        from agno.sandbox import _harness

        try:
            _harness._check_db(agent)
        except ValueError as error:
            raise ComponentRehydrationError(f"Agent '{id}' cannot run in its sandbox: {error}") from error
    return agent


def external_agent_from_config(
    config: Dict[str, Any],
    id: str,
    db: BaseDb,
    registry: Optional["Registry"] = None,
    strict: bool = False,
) -> "BaseExternalAgent":
    """Rebuild a stored external agent the way the db loaders rebuild an Agent."""
    from agno.agents.base import BaseExternalAgent

    agent = BaseExternalAgent.from_dict(config, registry=registry, strict=strict)
    return bind_loaded_agent(agent, id, db, config, strict)


def unavailable_external_agent(config: Dict[str, Any], id: str, db: BaseDb, reason: str) -> "BaseExternalAgent":
    """A stand-in for a stored external agent this process cannot rebuild.

    Listings keep it visible under its stored id, name and sdk; a run reports
    the reason instead of executing.
    """
    from agno.agents.unavailable import UnavailableExternalAgent

    sdk = config.get("sdk")
    name = config.get("name")
    description = config.get("description")
    return UnavailableExternalAgent(
        id=id,
        name=name if isinstance(name, str) else None,
        description=description if isinstance(description, str) else None,
        db=db,
        stored_sdk=sdk if isinstance(sdk, str) else "external",
        reason=reason,
    )


def save(
    agent: "BaseExternalAgent",
    *,
    db: Optional[BaseDb] = None,
    stage: str = "published",
    label: Optional[str] = None,
    notes: Optional[str] = None,
) -> Optional[int]:
    """Save the adapter as an agent component with a new config version."""
    db_ = db or agent.db
    if not db_:
        raise ValueError("Db not initialized or provided")
    if not isinstance(db_, BaseDb):
        raise ValueError("Async databases not yet supported for save(). Use a sync database.")

    if agent.id is None:
        agent.id = generate_id_from_name(agent.name)
    if agent.id in RESERVED_MANAGER_IDS:
        raise ValueError(_reserved_manager_id_message(agent.id))
    require_same_agent_kind(db_, agent.id, agent.sdk)

    config = to_dict(agent)
    try:
        db_.upsert_component(
            component_id=agent.id,
            component_type=ComponentType.AGENT,
            name=agent.name or agent.id,
            description=agent.description,
        )
        stored = db_.upsert_config(component_id=agent.id, config=config, label=label, stage=stage, notes=notes)
        return stored.get("version")
    except Exception as e:
        log_error(f"Error saving {type(agent).__name__} to database: {str(e)}")
        raise


def load(
    cls: Type["BaseExternalAgent"],
    id: str,
    *,
    db: BaseDb,
    registry: Optional["Registry"] = None,
    label: Optional[str] = None,
    version: Optional[int] = None,
    strict: bool = False,
    published_only: bool = False,
) -> Optional["BaseExternalAgent"]:
    """Load a stored adapter by id, resolving its references from the registry."""
    if id in RESERVED_MANAGER_IDS:
        raise ComponentRehydrationError(_reserved_manager_id_message(id))

    if published_only and version is None and label is None:
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
    return bind_loaded_agent(agent, id, db, config, strict)


def _thread_bound(db: Any) -> bool:
    """Whether the db's connections are private to the calling thread.

    SQLAlchemy serves an in-memory SQLite database from a SingletonThreadPool:
    every thread gets its own empty database, so work moved to a worker thread
    would read and write a store the caller never sees.
    """
    from sqlalchemy.pool import SingletonThreadPool

    return isinstance(getattr(getattr(db, "db_engine", None), "pool", None), SingletonThreadPool)


async def _off_loop(catalog_db: Any, func: Any, /, *args: Any, **kwargs: Any) -> Any:
    """Run a sync catalog call in a worker thread, unless the db is bound to this thread."""
    if _thread_bound(catalog_db):
        return func(*args, **kwargs)
    return await asyncio.to_thread(func, *args, **kwargs)


async def asave(
    agent: "BaseExternalAgent",
    *,
    db: Optional[BaseDb] = None,
    stage: str = "published",
    label: Optional[str] = None,
    notes: Optional[str] = None,
) -> Optional[int]:
    """Async variant of save; the component catalog is served by the sync db, off the event loop."""
    return await _off_loop(db or agent.db, save, agent, db=db, stage=stage, label=label, notes=notes)


async def aload(
    cls: Type["BaseExternalAgent"],
    id: str,
    *,
    db: BaseDb,
    registry: Optional["Registry"] = None,
    label: Optional[str] = None,
    version: Optional[int] = None,
    strict: bool = False,
    published_only: bool = False,
) -> Optional["BaseExternalAgent"]:
    """Async variant of load; the component catalog is served by the sync db, off the event loop."""
    return await _off_loop(
        db,
        load,
        cls,
        id,
        db=db,
        registry=registry,
        label=label,
        version=version,
        strict=strict,
        published_only=published_only,
    )


def delete(
    agent: "BaseExternalAgent",
    *,
    db: Optional[BaseDb] = None,
    hard_delete: bool = False,
    require_no_dependents: bool = True,
) -> bool:
    """Delete the adapter's component; soft by default, like Agent.delete."""
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


async def adelete(
    agent: "BaseExternalAgent",
    *,
    db: Optional[BaseDb] = None,
    hard_delete: bool = False,
    require_no_dependents: bool = True,
) -> bool:
    """Async variant of delete; the component catalog is served by the sync db, off the event loop."""
    return await _off_loop(
        db or agent.db, delete, agent, db=db, hard_delete=hard_delete, require_no_dependents=require_no_dependents
    )
