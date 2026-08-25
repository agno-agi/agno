from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from functools import cached_property
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterator, List, Optional, Set, Tuple, Type, Union
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from agno.db.base import BaseDb
from agno.models.base import Model
from agno.tools.function import RUNTIME_ONLY_FIELDS, Function, isolated_runtime_value
from agno.tools.toolkit import Toolkit
from agno.utils.log import log_warning
from agno.vectordb.base import VectorDb

if TYPE_CHECKING:
    from agno.agent import Agent
    from agno.team import Team
    from agno.workflow import Workflow

# A flat function name, or a (toolkit name, function name) qualified pair.
EntrypointKey = Union[str, Tuple[str, str]]
# The Function that owns the entrypoint, or the registered plain callable itself.
EntrypointSource = Union[Function, Callable]


class ToolSource(str, Enum):
    """How a tool entered the registry.

    DECLARED tools were registered directly on the registry and are buildable
    from Studio. DISCOVERED tools were found on a registered component's own
    tool list: they stay resolvable at rehydration, but Studio's palette policy
    refuses to wire them into new components unless explicitly allow-listed.
    """

    DECLARED = "declared"
    DISCOVERED = "discovered"


def _model_identity(model: Model) -> tuple:
    """Stable identity for catalog dedup: the provider class, display provider, and model id.

    The class (module + qualname) is included alongside the display ``provider`` string so that
    distinct classes sharing a provider string (e.g. OpenAIChat vs OpenAIResponses, or the Azure
    model classes -- all report provider "Azure") are not collapsed into a single catalog entry.
    """
    cls = type(model)
    return (cls.__module__, cls.__qualname__, getattr(model, "provider", None), getattr(model, "id", None))


def _memory_manager_resource_name(manager: Any) -> Optional[str]:
    """The name a memory manager is listed under in the registry listing.

    A manager without a name is listed under its id, so that is the string a
    caller selecting from the listing writes into a config.
    """
    return getattr(manager, "name", None) or getattr(manager, "id", None)


def _tool_resource_name(tool: Any) -> Optional[str]:
    """The top-level name a tool is claimed and judged under.

    Toolkits and Functions carry ``name``; a plain callable is known by
    ``__name__``. This is the key the build palette reads, so foldedness is
    tracked under exactly this string. A non-string name is no name at all:
    it can never match a requested tool name.
    """
    name = getattr(tool, "name", None) or getattr(tool, "__name__", None)
    return name if isinstance(name, str) and name else None


@dataclass
class Registry:
    """
    Registry is used to manage non serializable objects like tools, models, databases, vector databases,
    agents, teams, and workflows.
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
    # Names claimed by two distinct knowledge instances: lenient resolution
    # keeps the first, strict resolution refuses the ambiguity.
    _ambiguous_knowledge_names: Set[str] = field(default_factory=set, init=False, repr=False)
    # Names no deployer ever declared: they reached the registry only by being
    # discovered on a registered component. Such a tool stays resolvable at
    # rehydration but is not buildable by default -- Studio's palette policy
    # asks ``tool_is_declared``. This is a property of the NAME, not of an
    # instance: the palette selects tools by name, so a declaration of that
    # name puts it in the palette whichever order the two arrivals came in.
    undeclared_tool_names: Set[str] = field(default_factory=set, init=False, repr=False)
    # Knowledge a framework sync mirrored in for name resolution, as opposed to
    # the user registering it. Kept on the registry, not on the AgentOS that
    # mirrored, because a registry can be shared: any AgentOS asking must see
    # every mirror, or one OS's component-private knowledge would look
    # user-registered to another.
    _mirrored_knowledge: List[Any] = field(default_factory=list, init=False, repr=False)
    # LearningMachines a deployer declared for stored components to share.
    # Resolved by name, like knowledge: a component config carries
    # {"name": ...} and the registry supplies the live machine on load.
    learning: List[Any] = field(default_factory=list)
    # Names claimed by two distinct machines: lenient resolution keeps the
    # first, strict resolution refuses the ambiguity.
    _ambiguous_learning_names: Set[str] = field(default_factory=set, init=False, repr=False)
    memory_managers: List[Any] = field(default_factory=list)
    session_summary_managers: List[Any] = field(default_factory=list)
    # Code-defined agents, teams, and workflows (for rehydration)
    agents: List[Agent] = field(default_factory=list)
    teams: List[Team] = field(default_factory=list)
    workflows: List[Workflow] = field(default_factory=list)
    # The db behind the component catalog, named by the AgentOS holding this
    # registry (see declare_component_db). None once declared means this OS
    # has no db that can serve the catalog.
    component_db: Optional[BaseDb] = field(default=None, init=False, repr=False)
    component_db_declared: bool = field(default=False, init=False, repr=False)

    @cached_property
    def _entrypoint_lookup(self) -> Dict[EntrypointKey, EntrypointSource]:
        # Maps function name -> source: the Function that owns the entrypoint
        # (for Toolkit and Function tools) or the plain callable itself.
        # Toolkit functions are additionally indexed under a toolkit-qualified
        # tuple key (<toolkit name>, <function name>) so serialized dicts that
        # carry their owning toolkit's name (the "toolkit" key written at
        # serialization) resolve to the right toolkit even when two registry
        # toolkits share member names. A tuple never equals a string, so
        # qualified keys cannot collide with flat names -- including function
        # names that contain characters like dots.
        lookup: Dict[EntrypointKey, EntrypointSource] = {}

        def _entrypoint(source: EntrypointSource) -> Optional[Callable]:
            return source.entrypoint if isinstance(source, Function) else source

        def register(name: str, source: EntrypointSource) -> None:
            # The flat slot is keyed by name only, so two genuinely different
            # tools that share a name collapse to one slot (last wins). Dicts
            # qualified with their toolkit's name still resolve correctly, but
            # unqualified ones (legacy configs, plain callables) can't, so we
            # surface the collision for the user to disambiguate.
            existing = lookup.get(name)
            if existing is not None and existing is not source and _entrypoint(existing) is not _entrypoint(source):
                log_warning(
                    f"Registry: multiple distinct tools share the name '{name}'. "
                    "rehydrate_function() can only resolve one of them; give the tools "
                    "or toolkits distinct names to disambiguate."
                )
            lookup[name] = source

        for toolkit, name, source in self._iter_entrypoint_sources():
            register(name, source)
            if toolkit is not None and isinstance(toolkit.name, str) and toolkit.name:
                # A qualified slot collides only when two same-named toolkits
                # share a member name, and that collision has already warned on
                # the flat slot above -- so this write stays silent (last wins).
                lookup[(toolkit.name, name)] = source
        return lookup

    def _iter_entrypoint_sources(self) -> Iterator[Tuple[Optional[Toolkit], str, EntrypointSource]]:
        """Every (owning toolkit, name, source) registration, in order.

        The single source of truth for what claims an entrypoint slot:
        ``_entrypoint_lookup`` folds these into its dicts and ``_owner_index``
        replays them per batch, so the two can never disagree on a winner.
        """
        for tool in self.tools:
            if isinstance(tool, Toolkit):
                # get_functions() is the exposed subset -- the only functions
                # that are serialized or run, so only those claim a slot.
                for func in tool.get_functions().values():
                    if func.entrypoint is not None:
                        yield tool, func.name, func
            elif isinstance(tool, Function):
                if tool.entrypoint is not None:
                    yield None, tool.name, tool
            elif callable(tool):
                yield None, tool.__name__, tool

    def _owner_index(
        self,
    ) -> Tuple[Dict[EntrypointKey, Tuple[Optional[Toolkit], EntrypointSource]], Dict[int, Toolkit]]:
        """Slot owners and toolkit provenance, replayed from the registrations.

        The first map holds the (toolkit, source) a fresh lookup build would
        leave in every slot. Comparing a cached entry against its slot's owner
        detects every way the cache can go stale: a toolkit that rebuilt its
        functions dict (MCP toolkits replace every Function on connect), a
        member deleted after the cache was built, or a slot whose
        last-write-wins winner changed. A miss-only check catches none of
        those, because the stale entry still *hits*.

        The second map answers a different question: which live Toolkit holds
        this exact Function object. Slot ownership cannot answer it -- a
        toolkit member also registered directly owns its flat slot as a direct
        registration, yet the toolkit still holds the object, and its guidance
        still belongs to a component that loaded the member. Freshness is the
        slot's; provenance is the object's.

        Built once per rehydration batch, so a component load pays one walk of
        the registrations rather than one per tool dict.
        """
        index: Dict[EntrypointKey, Tuple[Optional[Toolkit], EntrypointSource]] = {}
        by_identity: Dict[int, Toolkit] = {}
        for toolkit, name, source in self._iter_entrypoint_sources():
            index[name] = (toolkit, source)
            if toolkit is not None:
                by_identity[id(source)] = toolkit
                if isinstance(toolkit.name, str) and toolkit.name:
                    index[(toolkit.name, name)] = (toolkit, source)
        return index, by_identity

    def rehydrate_function(self, func_dict: Dict[str, Any]) -> Function:
        """Reconstruct a Function from dict, reattaching its entrypoint.

        Dicts that carry their owning toolkit's name (the "toolkit" key written
        at serialization) resolve via the toolkit-qualified key first, so
        same-named functions from different toolkits bind to the right
        entrypoint. The flat function name stays as the fallback for configs
        saved before qualification and for functions whose toolkit is no longer
        in the registry.
        """
        return self._rehydrate_function(func_dict, {"rebuilt": False})

    @staticmethod
    def _is_function_config(func_dict: Dict[str, Any]) -> bool:
        """Whether ``Function.to_dict()`` could have written this dict.

        Positive identification: ``name`` and ``parameters`` are always
        written (``parameters`` has a non-None default, and ``to_dict`` only
        drops None values), and no ``SERIALIZED_FIELDS`` key is ``type`` or
        ``input_schema``. Provider-native tool dicts miss on one of these --
        OpenAI-style builtins carry a top-level ``type``, Anthropic-style
        custom tools carry ``input_schema`` and no ``parameters``. Anything
        else in a tools list is the provider's to interpret, not ours to
        parse.
        """
        return (
            "name" in func_dict
            and "parameters" in func_dict
            and "type" not in func_dict
            and "input_schema" not in func_dict
        )

    def rehydrate_functions(
        self, func_dicts: List[Dict[str, Any]], strict: bool = False
    ) -> List[Union[Function, Dict[str, Any]]]:
        """Rehydrate a batch of persisted tool dicts, sharing one cache-rebuild budget.

        With strict=True a toolkit-qualified reference resolves only from its
        own toolkit; the flat-name fallback that may bind a same-named function
        from a different toolkit is reserved for lenient loads.

        A component load rehydrates every tool in its config; one rebuild of the
        entrypoint lookup per batch is enough to pick up late-registered
        functions, so repeated misses within a load don't each pay a rebuild.

        A tools list can also carry provider-run tools persisted as plain
        dicts. Those run inside the model provider, not the framework: there
        is no entrypoint to reattach, so anything that is not positively a
        serialized Function -- see ``_is_function_config`` -- passes through
        unchanged, in place. A dict that looks like one but fails validation
        passes through too: one unparseable tool must not take down the whole
        component load.
        """
        rebuild_state: Dict[str, Any] = {"rebuilt": False}
        rehydrated: List[Union[Function, Dict[str, Any]]] = []
        for func_dict in func_dicts:
            if not self._is_function_config(func_dict):
                rehydrated.append(func_dict)
                continue
            try:
                rehydrated.append(self._rehydrate_function(func_dict, rebuild_state, strict=strict))
            except ValidationError as e:
                if strict:
                    from agno.exceptions import ComponentRehydrationError

                    raise ComponentRehydrationError(
                        f"Tool dict '{func_dict.get('name')}' is a serialized Function that does "
                        f"not validate ({e.error_count()} error(s)); the stored config is corrupt. "
                        "Re-save the component, or pass strict=False to pass the dict through to "
                        "the model provider unchanged."
                    ) from e
                log_warning(
                    f"Registry: tool dict '{func_dict.get('name')}' looks like a serialized "
                    f"Function but does not validate as one ({e.error_count()} error(s)); "
                    "passing it through to the model provider unchanged."
                )
                rehydrated.append(func_dict)
        return rehydrated

    def _rehydrate_function(
        self, func_dict: Dict[str, Any], rebuild_state: Dict[str, Any], strict: bool = False
    ) -> Function:
        func = Function.from_dict(func_dict)
        toolkit_name = func_dict.get("toolkit")
        if isinstance(toolkit_name, str) and toolkit_name:
            # Keep the attribution on the object so a load -> save round trip
            # re-stamps the "toolkit" key even though the loaded component holds
            # bare Functions instead of Toolkits.
            func.owning_toolkit = toolkit_name

        owner_maps = rebuild_state.get("owners")
        if owner_maps is None:
            owner_maps = rebuild_state["owners"] = self._owner_index()
        owners, toolkit_by_identity = owner_maps

        def lookup(key: EntrypointKey) -> Tuple[Optional[EntrypointSource], Optional[Toolkit]]:
            # Resolution serves the slot's owner: the same answer a fresh cache
            # build would give. The cached lookup is compared against it to
            # decide when to rebuild -- Toolkits can gain functions after the
            # lookup is first built (MCP toolkits only register their functions
            # once connected), so a miss may just mean the cache is stale, and
            # a hit goes stale the same way when a toolkit rebuilds or drops
            # its functions, or a slot's last-write-wins winner changes.
            # Rebuild once per batch when the cache disagrees, so collision
            # warnings re-surface and later batches start warm, and not at all
            # when a rebuild could not help (the key has no owner in the
            # current registrations, so it would miss too).
            owner_toolkit, owner_source = owners.get(key, (None, None))
            if not rebuild_state["rebuilt"] and self._entrypoint_lookup.get(key) is not owner_source:
                self.__dict__.pop("_entrypoint_lookup", None)
                rebuild_state["rebuilt"] = True
                _ = self._entrypoint_lookup
            return owner_source, owner_toolkit

        source: Optional[EntrypointSource] = None
        source_owner: Optional[Toolkit] = None
        resolved_as_recorded = func.owning_toolkit is None
        if func.owning_toolkit is not None:
            # A qualified miss rebuilds before falling back to the flat name:
            # the flat slot may hold a same-named function from a *different*
            # toolkit while the right one simply hasn't populated the cache yet.
            source, source_owner = lookup((func.owning_toolkit, func.name))
            resolved_as_recorded = source is not None
        # A strict load keeps a qualified reference bound to its own toolkit:
        # a same-named function from another toolkit is a different tool.
        if source is None and (func.owning_toolkit is None or not strict):
            source, source_owner = lookup(func.name)
            if source is not None and func.owning_toolkit is not None:
                # The recorded toolkit could not be honored, so the flat slot's
                # same-named function -- possibly from a different toolkit -- is
                # being bound instead.
                log_warning(
                    f"Registry: toolkit '{func.owning_toolkit}' does not provide '{func.name}' "
                    "in this registry; binding the same-named function found under the flat "
                    "name instead. If the toolkit was renamed, update the registry or re-save "
                    "the component."
                )
        if isinstance(source, Function):
            func.entrypoint = source.entrypoint
            # Behavior the storage layer never writes comes from the live
            # registry Function, so registry-side edits apply on the next
            # component load. See RUNTIME_ONLY_FIELDS for what and why.
            for field_name in RUNTIME_ONLY_FIELDS:
                setattr(func, field_name, isolated_runtime_value(getattr(source, field_name)))
            # Only when the bound function is the one the config named, or the
            # config named no toolkit at all. A config whose recorded toolkit
            # has left the registry binds the flat slot, which may belong to a
            # different toolkit, and that toolkit's guidance is not this
            # function's to carry.
            #
            # The slot's owner is the primary attribution; the identity map is
            # the fallback for a flat slot owned by a direct registration of an
            # object a Toolkit also holds -- provenance follows the object.
            source_toolkit = source_owner if source_owner is not None else toolkit_by_identity.get(id(source))
            if not resolved_as_recorded:
                source_toolkit = None
            if source_toolkit is not None:
                # Keep the exact live Toolkit available to instruction
                # collection. Every member points to the same object, so the
                # collector can add toolkit-level guidance once without
                # copying it into persisted Function dictionaries.
                #
                # The attribution is deliberately not written back onto an
                # unqualified config. Identity resolution already reaches the
                # Toolkit without a recorded name, and stamping one would tie
                # the config to that name: a later rename would then take the
                # qualified path, miss, and lose the guidance the unstamped
                # config still finds.
                func.source_toolkit = source_toolkit
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

    def add_tool(self, tool: Any, source: Union[ToolSource, str] = ToolSource.DECLARED) -> None:
        """Add a tool unless an equivalent one is already present.

        ``source`` says how the tool arrived: ``ToolSource.DECLARED`` (the
        default) for tools registered directly, ``ToolSource.DISCOVERED`` for
        tools found on a registered component. The equivalent plain strings are
        accepted.

        The source decides one thing: whether the tool's *name* is in the build
        palette (see ``tool_is_declared``). A declaration always wins over a
        discovery, in either order, so the name a deployer registers directly --
        in the constructor or through this method -- stays buildable even when a
        component carries a same-named tool the AgentOS walk finds. A discovery
        marks a name only when no other tool already claims it, which is what
        keeps that rule order-independent.

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

        Deduplication and the source decision are independent. A tool that
        dedupes away still records its source, because a deployer declaring a
        toolkit an agent already carries is declaring the name buildable --
        whether or not the equivalent instance was folded in first.

        Adding a tool invalidates the ``_entrypoint_lookup`` cache so that
        ``rehydrate_function`` rebuilds it and sees the new tool.
        """
        if not (isinstance(tool, (Toolkit, Function)) or callable(tool)):
            return

        name = _tool_resource_name(tool)
        # Read before the add, so the tool being added never counts as its own
        # claim: this asks whether some *other* tool already owns the name.
        # Only a fold consults it, so the scan is skipped on declarations.
        name_already_claimed = (
            source == ToolSource.DISCOVERED
            and name is not None
            and any(_tool_resource_name(t) == name for t in self.tools)
        )

        if not self._is_duplicate_tool(tool):
            self.tools.append(tool)
            self.__dict__.pop("_entrypoint_lookup", None)

        if name is None:
            return
        if source == ToolSource.DISCOVERED:
            # Discovery makes every registered agent's own tools resolvable at
            # rehydration; resolvable is not the same as buildable. A name a
            # declaration already claims stays buildable: two toolkits can
            # share a name without sharing a function set, and discovering the
            # second must not take the declared one out of the palette.
            if not name_already_claimed:
                self.undeclared_tool_names.add(name)
        elif source == ToolSource.DECLARED:
            # Declaring is the deployer putting the name in the palette, even
            # when the discovery got there first and even when this instance
            # dedupes against the discovered one.
            self.undeclared_tool_names.discard(name)

    def tool_is_declared(self, name: str) -> bool:
        """Whether a deployer declared this tool name, so Studio may build with it.

        A name reaches the registry either because someone registered it or
        because it was discovered on a registered component. Only the first is
        an instruction to make it buildable; the second just has to resolve at
        rehydration.
        """
        return name not in self.undeclared_tool_names

    def _is_duplicate_tool(self, tool: Any) -> bool:
        """Whether an equivalent tool is already registered (see ``add_tool``)."""
        if isinstance(tool, Toolkit):
            key = (type(tool), tool.name, frozenset(tool.functions))
            for existing in self.tools:
                if existing is tool:
                    return True
                if (
                    isinstance(existing, Toolkit)
                    and (type(existing), existing.name, frozenset(existing.functions)) == key
                ):
                    return True
            return False

        for existing in self.tools:
            if existing is tool:
                return True
            try:
                if existing == tool:
                    return True
            except Exception:
                # A callable with a pathological __eq__ should not block the add;
                # fall back to keeping both, which is the safe direction.
                continue
        return False

    def declare_component_db(self, db: Any) -> None:
        """State which database backs the component catalog.

        AgentOS calls this with its own db. A db that is not a synchronous
        ``BaseDb`` -- async, or remote -- cannot serve the catalog, and is
        declared as None rather than left undeclared: an undeclared registry
        falls back to ``dbs[0]``, and that list holds whatever the component
        tree carried, so the fallback can bind a Studio toolkit to an
        agent-private session db and write the catalog where no OS surface
        reads it.

        """
        self.component_db = db if isinstance(db, BaseDb) else None
        self.component_db_declared = True

    def resolve_component_db(self) -> Optional[BaseDb]:
        """The database a component-catalog toolkit should use when given none.

        A declaration wins outright, including a declared None. Without one --
        no AgentOS in the picture, a toolkit driven straight from Python --
        the head of ``dbs`` is the long-standing fallback.
        """
        if self.component_db_declared:
            return self.component_db
        return self.dbs[0] if self.dbs else None

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

    def add_function(self, func: Any) -> None:
        """Add a plain callable unless one with the same name is already present.

        Workflow step executors, evaluators, selectors and end conditions
        resolve by function name at rehydration. The first callable under a
        name wins; a distinct same-named callable is reported, since it would
        be shadowed.
        """
        if not callable(func) or not getattr(func, "__name__", None):
            return
        existing = self.get_function(func.__name__)
        if existing is not None:
            if existing is not func:
                log_warning(
                    f"Registry: multiple distinct callables share the name '{func.__name__}'; "
                    "keeping the first. Rename one to avoid it being shadowed."
                )
            return
        self.functions.append(func)

    def add_knowledge(self, knowledge: Any, mirrored: bool = False) -> None:
        """Add a knowledge instance unless one with the same name is already present.

        Knowledge resolves by name at rehydration, so only named instances are
        registrable. The first instance under a name wins; a distinct
        same-named instance is reported, since it would be shadowed.

        ``mirrored`` marks an instance a framework sync added for name
        resolution rather than the user registering it; mirrored knowledge is
        not a knowledge-route source on any AgentOS sharing this registry. An
        explicit (non-mirrored) add of an instance that is already present
        promotes it to user provenance: the user registering it by hand is the
        grant a mirror is not.
        """
        name = getattr(knowledge, "name", None)
        if knowledge is None or name is None:
            return
        existing = self.get_knowledge(name)
        if existing is not None:
            if existing is not knowledge:
                self._ambiguous_knowledge_names.add(name)
                log_warning(
                    f"Registry: multiple distinct knowledge instances share name '{name}'; "
                    "keeping the first for lenient loads. Strict loads refuse the ambiguity: "
                    "give the instances distinct names."
                )
            elif not mirrored:
                self._mirrored_knowledge = [kb for kb in self._mirrored_knowledge if kb is not knowledge]
            return
        self.knowledge.append(knowledge)
        if mirrored:
            self._mirrored_knowledge.append(knowledge)

    def knowledge_is_mirrored(self, knowledge: Any) -> bool:
        """Whether ``knowledge`` is in the registry only because a sync mirrored it."""
        return any(knowledge is kb for kb in self._mirrored_knowledge)

    def add_learning(self, machine: Any) -> None:
        """Add a LearningMachine unless one with the same name is already present.

        A machine resolves by name at rehydration, so only named machines are
        registrable. The first machine under a name wins; a distinct
        same-named machine is reported, since it would be shadowed.
        """
        name = getattr(machine, "name", None)
        if machine is None or not isinstance(name, str) or not name:
            return
        existing = self.get_learning(name)
        if existing is not None:
            if existing is not machine:
                self._ambiguous_learning_names.add(name)
                log_warning(
                    f"Registry: multiple distinct learning machines share name '{name}'; "
                    "keeping the first for lenient loads. Strict loads refuse the ambiguity: "
                    "give the machines distinct names."
                )
            return
        self.learning.append(machine)

    def add_schema(self, schema: Any) -> None:
        """Add an input/output schema class unless one with the same name is already present.

        Schemas resolve by class name at rehydration. Inline dict schemas are
        not registrable and ride through serialization on their own.
        """
        if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
            return
        existing = self.get_schema(schema.__name__)
        if existing is not None:
            if existing is not schema:
                log_warning(
                    f"Registry: multiple distinct schema classes share the name '{schema.__name__}'; "
                    "keeping the first. Rename one to avoid it being shadowed."
                )
            return
        self.schemas.append(schema)

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

    def knowledge_name_is_ambiguous(self, name: str) -> bool:
        """Whether two distinct knowledge instances claim ``name``.

        Covers both construction paths: instances handed to the constructor
        (scanned here) and instances add_knowledge refused to append (recorded
        in the ambiguity set).
        """
        if name in self._ambiguous_knowledge_names:
            return True
        matches = [k for k in self.knowledge if getattr(k, "name", None) == name]
        return len(matches) > 1 and any(match is not matches[0] for match in matches)

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

    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """Get a workflow by id from the registry."""
        if self.workflows:
            return next((w for w in self.workflows if getattr(w, "id", None) == workflow_id), None)
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

    def get_workflow_ids(self) -> Set[str]:
        """Get the set of all workflow IDs in this registry."""
        if self.workflows:
            return {wid for w in self.workflows if (wid := getattr(w, "id", None)) is not None}
        return set()

    def get_knowledge_names(self) -> Set[str]:
        """Get the set of all knowledge names in this registry."""
        if self.knowledge:
            return {kn for k in self.knowledge if (kn := getattr(k, "name", None)) is not None}
        return set()

    def learning_name_is_ambiguous(self, name: str) -> bool:
        """Whether two distinct learning machines claim ``name``.

        Covers both construction paths: machines handed to the constructor
        (scanned here) and machines add_learning refused to append (recorded
        in the ambiguity set).
        """
        if name in self._ambiguous_learning_names:
            return True
        matches = [m for m in self.learning if getattr(m, "name", None) == name]
        return len(matches) > 1 and any(match is not matches[0] for match in matches)

    def get_learning(self, name: str) -> Optional[Any]:
        """Get a learning machine by name from the registry."""
        if self.learning:
            return next((m for m in self.learning if getattr(m, "name", None) == name), None)
        return None

    def get_learning_names(self) -> Set[str]:
        """Get the set of all learning machine names in this registry."""
        if self.learning:
            return {mn for m in self.learning if isinstance((mn := getattr(m, "name", None)), str) and mn}
        return set()

    def get_memory_manager(self, manager_id: str) -> Optional[Any]:
        """Get a memory manager by id."""
        if self.memory_managers:
            return next(
                (m for m in self.memory_managers if getattr(m, "id", None) == manager_id),
                None,
            )
        return None

    def get_memory_manager_by_name(self, name: str) -> Optional[Any]:
        """Get a memory manager by the name it is listed under."""
        if self.memory_managers:
            return next(
                (m for m in self.memory_managers if _memory_manager_resource_name(m) == name),
                None,
            )
        return None

    def memory_manager_name_is_ambiguous(self, name: str) -> bool:
        """Whether two distinct memory managers are listed under ``name``."""
        if not self.memory_managers:
            return False
        matches = [m for m in self.memory_managers if _memory_manager_resource_name(m) == name]
        return len(matches) > 1 and any(match is not matches[0] for match in matches)

    def memory_manager_ids_for_name(self, name: str) -> List[str]:
        """The ids of every memory manager listed under ``name``, in registration order.

        A caller that found a name ambiguous uses this to say which managers
        competed for it. A manager with no id contributes nothing: it cannot be
        named in an answer, and it is already reachable by the name itself.
        """
        if not self.memory_managers:
            return []
        return [
            str(mid)
            for m in self.memory_managers
            if _memory_manager_resource_name(m) == name and (mid := getattr(m, "id", None)) is not None
        ]

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
        """Get the set of all agent, team, and workflow IDs in this registry.

        The union is untyped: a consumer excluding "registry-owned" ids from a
        listing excludes them across component types. Per-type consumers should
        use the typed getters instead."""
        return self.get_agent_ids() | self.get_team_ids() | self.get_workflow_ids()
