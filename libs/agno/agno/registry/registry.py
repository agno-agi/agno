from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set, Type
from uuid import uuid4

from pydantic import BaseModel

from agno.db.base import BaseDb
from agno.models.base import Model
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit
from agno.utils.log import log_warning
from agno.vectordb.base import VectorDb

if TYPE_CHECKING:
    from agno.agent import Agent
    from agno.team import Team


def _model_identity(model: Model) -> tuple:
    """Stable identity for catalog dedup: the provider class, display provider, and model id.

    The class (module + qualname) is included alongside the display ``provider`` string so that
    distinct classes sharing a provider string (e.g. OpenAIChat vs OpenAIResponses, or the Azure
    model classes -- all report provider "Azure") are not collapsed into a single catalog entry.
    """
    cls = type(model)
    return (cls.__module__, cls.__qualname__, getattr(model, "provider", None), getattr(model, "id", None))


@dataclass
class Registry:
    """
    Registry is used to manage non serializable objects like tools, models, databases, vector databases,
    agents, and teams.
    """

    name: Optional[str] = None
    description: Optional[str] = None
    id: str = field(default_factory=lambda: str(uuid4()))
    tools: List[Any] = field(default_factory=list)
    models: List[Model] = field(default_factory=list)
    dbs: List[BaseDb] = field(default_factory=list)
    vector_dbs: List[VectorDb] = field(default_factory=list)
    schemas: List[Type[BaseModel]] = field(default_factory=list)
    functions: List[Callable] = field(default_factory=list)
    knowledge: List[Any] = field(default_factory=list)
    memory_managers: List[Any] = field(default_factory=list)
    session_summary_managers: List[Any] = field(default_factory=list)
    # Code-defined agents and teams (for workflow rehydration)
    agents: List[Agent] = field(default_factory=list)
    teams: List[Team] = field(default_factory=list)

    @cached_property
    def _entrypoint_lookup(self) -> Dict[str, Any]:
        # Maps function name -> source: the Function that owns the entrypoint
        # (for Toolkit and Function tools) or the plain callable itself.
        lookup: Dict[str, Any] = {}

        def _entrypoint(source: Any) -> Optional[Callable]:
            return source.entrypoint if isinstance(source, Function) else source

        def register(name: str, source: Any) -> None:
            # This lookup is keyed by name only, so two genuinely different tools
            # that share a name collapse to one slot (last wins). We can't resolve
            # that from a serialized function name alone, but we can surface it so
            # the user can give the tools distinct names.
            existing = lookup.get(name)
            if existing is not None and existing is not source and _entrypoint(existing) is not _entrypoint(source):
                log_warning(
                    f"Registry: multiple distinct tools share the name '{name}'. "
                    "rehydrate_function() can only resolve one of them; give the tools "
                    "or toolkits distinct names to disambiguate."
                )
            lookup[name] = source

        for tool in self.tools:
            if isinstance(tool, Toolkit):
                for func in tool.functions.values():
                    if func.entrypoint is not None:
                        register(func.name, func)
            elif isinstance(tool, Function):
                if tool.entrypoint is not None:
                    register(tool.name, tool)
            elif callable(tool):
                register(tool.__name__, tool)
        return lookup

    def rehydrate_function(self, func_dict: Dict[str, Any]) -> Function:
        """Reconstruct a Function from dict, reattaching its entrypoint."""
        func = Function.from_dict(func_dict)
        source = self._entrypoint_lookup.get(func.name)
        if source is None:
            # Toolkits can gain functions after the lookup is first built -- MCP
            # toolkits only register their functions once connected -- so a miss
            # may just mean the cache is stale. Rebuild once and retry.
            self.__dict__.pop("_entrypoint_lookup", None)
            source = self._entrypoint_lookup.get(func.name)
        if isinstance(source, Function):
            func.entrypoint = source.entrypoint
            # Entrypoints built for a fixed schema (e.g. MCP call proxies) must
            # not be re-introspected at run time: processing would rebuild the
            # schema's `required` list from the proxy's signature.
            func.skip_entrypoint_processing = source.skip_entrypoint_processing
        else:
            func.entrypoint = source
        if func.entrypoint is None:
            log_warning(
                f"Registry: no tool named '{func.name}' found while rehydrating; "
                "the function will have no entrypoint and cannot be executed. "
                "Make sure the tool is in the registry and, for MCP toolkits, connected."
            )
        return func

    def add_model(self, model: Any) -> None:
        """Add a model unless an equivalent one (same provider class and id) is already present.

        Models of the same class that share an id are interchangeable catalog entries, so
        duplicates are collapsed. Models of different classes are kept separate even when their
        display ``provider`` string and id match -- e.g. ``OpenAIChat`` vs ``OpenAIResponses``
        (both report provider "OpenAI") or the three distinct Azure model classes (all report
        provider "Azure"). Non-Model values (e.g. plain string ids) are ignored.
        """
        if not isinstance(model, Model):
            return
        key = _model_identity(model)
        for existing in self.models:
            if existing is model:
                return
            if _model_identity(existing) == key:
                return
        self.models.append(model)

    def add_tool(self, tool: Any) -> None:
        """Add a tool unless an equivalent one is already present.

        Deduplication depends on the kind of tool, because they duplicate for
        different reasons:

        - ``Toolkit`` instances are re-created at call sites (``DuckDuckGoTools()``
          written in two places yields two distinct objects), so they dedupe
          structurally by ``(type, name, function names)``. The first matching
          instance wins deterministically: user-declared registry tools are added
          before primitives are walked, and primitives are walked in order, so a
          later matching instance is skipped. This is expected (re-instantiating a
          default toolkit in two places is common), so the skip is silent. The
          trade-off is accepted: rehydration resolves
          entrypoints by function name globally (see ``_entrypoint_lookup``), so
          only one instance can ever back a given name regardless of dedup -- two
          toolkits that differ only in non-functional config (api keys, timeouts,
          region) collapse to the first, and that is the instance used at
          rehydration.
        - ``Function`` and plain callables are defined once, so referencing them in
          two places yields the *same* object; they dedupe by equality. ``==``
          falls back to identity for functions, lambdas and ``functools.partial``
          (so genuinely distinct callables are never merged on a shared name) while
          additionally catching bound methods, which build a fresh object on every
          attribute access but compare equal by ``(__self__, __func__)``.

        Adding a tool invalidates the ``_entrypoint_lookup`` cache so that
        ``rehydrate_function`` rebuilds it and sees the new tool.
        """
        if not (isinstance(tool, (Toolkit, Function)) or callable(tool)):
            return

        if isinstance(tool, Toolkit):
            key = (type(tool), tool.name, frozenset(tool.functions))
            for existing in self.tools:
                if existing is tool:
                    return
                if (
                    isinstance(existing, Toolkit)
                    and (type(existing), existing.name, frozenset(existing.functions)) == key
                ):
                    return
        else:
            for existing in self.tools:
                if existing is tool:
                    return
                try:
                    if existing == tool:
                        return
                except Exception:
                    # A callable with a pathological __eq__ should not block the add;
                    # fall back to keeping both, which is the safe direction.
                    continue

        self.tools.append(tool)
        self.__dict__.pop("_entrypoint_lookup", None)

    def add_db(self, db: Any) -> None:
        """Add a database unless one with the same id (or the same instance) is already present.

        Only synchronous ``BaseDb`` instances are tracked, matching the registry's
        db rehydration which is synchronous (see ``get_db``).
        """
        if not isinstance(db, BaseDb):
            return
        db_id = getattr(db, "id", None)
        if db_id is not None:
            for existing in self.dbs:
                if existing is db:
                    return
                if getattr(existing, "id", None) == db_id:
                    log_warning(
                        f"Registry: multiple distinct databases share id '{db_id}'; keeping the first. "
                        "Give them distinct ids to avoid one shadowing the other."
                    )
                    return
        elif any(d is db for d in self.dbs):
            return
        self.dbs.append(db)

    def add_vector_db(self, vector_db: Any) -> None:
        """Add a vector db unless one with the same id/name (or the same instance) is already present."""
        if not isinstance(vector_db, VectorDb):
            return
        key = getattr(vector_db, "id", None) or getattr(vector_db, "name", None)
        if key is not None:
            for existing in self.vector_dbs:
                if existing is vector_db:
                    return
                if (getattr(existing, "id", None) or getattr(existing, "name", None)) == key:
                    log_warning(
                        f"Registry: multiple distinct vector dbs share '{key}'; keeping the first. "
                        "Give them distinct ids/names to avoid one shadowing the other."
                    )
                    return
        elif any(v is vector_db for v in self.vector_dbs):
            return
        self.vector_dbs.append(vector_db)

    def get_schema(self, name: str) -> Optional[Type[BaseModel]]:
        """Get a schema by name."""
        if self.schemas:
            return next((s for s in self.schemas if s.__name__ == name), None)
        return None

    def get_db(self, db_id: str) -> Optional[BaseDb]:
        """Get a database by id from the registry.

        Args:
            db_id: The database id to look up

        Returns:
            The database instance if found, None otherwise
        """
        if self.dbs:
            return next((db for db in self.dbs if db.id == db_id), None)
        return None

    def get_model(self, model_id: str, provider: Optional[str] = None, name: Optional[str] = None) -> Optional[Model]:
        """Get a registered model instance by id, disambiguating by provider/name when given.

        Returns the live, fully-configured instance the user registered. Reconstructing a model
        from its serialized config only round-trips ``id``/``name``/``provider`` (see
        ``Model.to_dict``), so connection params like ``azure_endpoint``/``base_url`` and any
        credentials are lost. Preferring the registered instance keeps those intact.

        ``provider`` and ``name`` are matched only when supplied, so distinct provider classes that
        share an id (e.g. OpenAIChat vs OpenAIResponses, or the Azure model classes -- all report
        provider "Azure") resolve to the right instance. Returns None when nothing matches, letting
        the caller fall back to rebuilding from the serialized dict.
        """
        if not self.models or not model_id:
            return None
        for model in self.models:
            if getattr(model, "id", None) != model_id:
                continue
            if provider is not None and getattr(model, "provider", None) != provider:
                continue
            if name is not None and getattr(model, "name", None) != name:
                continue
            return model
        return None

    def get_function(self, name: str) -> Optional[Callable]:
        return next((f for f in self.functions if f.__name__ == name), None)

    def get_knowledge(self, name: str) -> Optional[Any]:
        """Get a knowledge instance by name from the registry."""
        if self.knowledge:
            return next((k for k in self.knowledge if getattr(k, "name", None) == name), None)
        return None

    def get_agent(self, agent_id: str) -> Optional[Agent]:
        """Get an agent by id from the registry."""
        if self.agents:
            return next((a for a in self.agents if getattr(a, "id", None) == agent_id), None)
        return None

    def get_team(self, team_id: str) -> Optional[Team]:
        """Get a team by id from the registry."""
        if self.teams:
            return next((t for t in self.teams if getattr(t, "id", None) == team_id), None)
        return None

    def get_agent_ids(self) -> Set[str]:
        """Get the set of all agent IDs in this registry."""
        if self.agents:
            return {aid for a in self.agents if (aid := getattr(a, "id", None)) is not None}
        return set()

    def get_team_ids(self) -> Set[str]:
        """Get the set of all team IDs in this registry."""
        if self.teams:
            return {tid for t in self.teams if (tid := getattr(t, "id", None)) is not None}
        return set()

    def get_knowledge_names(self) -> Set[str]:
        """Get the set of all knowledge names in this registry."""
        if self.knowledge:
            return {kn for k in self.knowledge if (kn := getattr(k, "name", None)) is not None}
        return set()

    def get_memory_manager(self, manager_id: str) -> Optional[Any]:
        """Get a memory manager by id."""
        if self.memory_managers:
            return next(
                (m for m in self.memory_managers if getattr(m, "id", None) == manager_id),
                None,
            )
        return None

    def get_session_summary_manager(self, manager_id: str) -> Optional[Any]:
        """Get a session summary manager by id."""
        if self.session_summary_managers:
            return next(
                (m for m in self.session_summary_managers if getattr(m, "id", None) == manager_id),
                None,
            )
        return None

    def get_memory_manager_ids(self) -> Set[str]:
        """Get the set of all memory manager ids."""
        if self.memory_managers:
            return {mid for m in self.memory_managers if (mid := getattr(m, "id", None)) is not None}
        return set()

    def get_session_summary_manager_ids(self) -> Set[str]:
        """Get the set of all session summary manager ids."""
        if self.session_summary_managers:
            return {mid for m in self.session_summary_managers if (mid := getattr(m, "id", None)) is not None}
        return set()

    def get_all_component_ids(self) -> Set[str]:
        """Get the set of all agent and team IDs in this registry."""
        return self.get_agent_ids() | self.get_team_ids()
