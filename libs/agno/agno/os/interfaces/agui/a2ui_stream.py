"""What an A2UI generation tool needs from the request it is serving, and
what can be known about the agent serving it.

A generation tool is built once, when the agent is defined, but everything it
needs is per-request: the catalog the client registered, the conversation to
look through for a surface to edit, and somewhere to send render progress. A
context variable carries them, because there is no argument the tool could take
that the model would not also see.

Nothing here depends on ``ag-ui-a2ui-toolkit``: the router and the stream mapper
are imported on every AG-UI request, whether or not A2UI is installed or used.
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from difflib import get_close_matches
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, FrozenSet, List, Mapping, Optional, Set, TypedDict, Union, cast

from agno.tools.function import Function
from agno.tools.toolkit import Toolkit
from agno.utils.log import log_warning

if TYPE_CHECKING:
    from ag_ui_a2ui_toolkit import A2UIGuidelines


class A2UIGenerationFunction(Function):
    """An A2UI generation tool.

    A distinct type so the router can tell that a run may generate surfaces and
    arrange to interleave their render progress, and so a tool the developer
    wired themselves is never injected over. It lives here rather than beside
    the generation code so that recognizing one costs no toolkit import.
    """


class A2UIRenderStream:
    """A buffer of render fragments plus a signal that some are waiting.

    Deliberately not an ``asyncio.Queue``: the stream mapper has to wait on
    this and on the agent's next event at the same time, and cancelling a
    pending ``Queue.get`` can consume an item as it goes. Waiting on a signal
    consumes nothing, so no fragment can be lost in the race.
    """

    def __init__(self) -> None:
        self._pending: List[Dict[str, Any]] = []
        self._signal = asyncio.Event()

    def push(self, payload: Dict[str, Any]) -> None:
        self._pending.append(payload)
        self._signal.set()

    def drain(self) -> List[Dict[str, Any]]:
        pending, self._pending = self._pending, []
        self._signal.clear()
        return pending

    async def wait(self) -> None:
        await self._signal.wait()


@dataclass
class A2UIRun:
    """The A2UI half of one AG-UI request.

    ``state`` holds the component catalog the client forwarded, in the shape the
    shared toolkit reads. ``messages`` is the conversation as the client sent
    it, which is where an earlier surface is found when the model asks to edit
    one; the agent's own run history covers only the turn in progress.
    """

    render_stream: Optional[A2UIRenderStream] = None
    state: Optional[Dict[str, Any]] = None
    messages: List[Any] = field(default_factory=list)


#: The A2UI inputs for the request being served, read by the generation tool.
current_a2ui_run: ContextVar[Optional[A2UIRun]] = ContextVar("agno_agui_a2ui_run", default=None)


class ToolPresence(Enum):
    """Whether a tool is on an entity, where "cannot tell" is a real answer.

    A tools list can be a callable the agent resolves when it runs, and what
    that will build cannot be read without running it. Reported as ABSENT, one
    unknowable case had two callers take two different wrong turns from the
    same wrong answer, so it is a value of its own and every caller has to say
    what it does about not knowing.
    """

    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class EntityTools:
    """One reading of the tools an agent or team was defined with.

    Both questions the A2UI interface asks are answered from this single walk:
    whether the entity already generates surfaces, and whether a name is
    taken. They were two functions with independently written cases, which is
    how a tool shape one could read and the other could not came to give a
    caller a confidently wrong answer.
    """

    names: FrozenSet[str] = frozenset()
    generation_tool_found: bool = False
    #: False when part of the list could not be read, which is what makes
    #: ABSENT unsayable: nothing was ruled out, it was only not seen.
    fully_read: bool = True
    #: The same for a team member's own tools, kept apart because it answers
    #: only one of the two questions: a member's generation is this team's
    #: generation, while what a member calls its tools cannot collide with a
    #: tool added to the leader.
    members_fully_read: bool = True

    def generates_a2ui(self) -> ToolPresence:
        """Whether a run on this entity may produce an A2UI surface itself."""
        if self.generation_tool_found:
            return ToolPresence.PRESENT
        if self.fully_read and self.members_fully_read:
            return ToolPresence.ABSENT
        return ToolPresence.UNKNOWN

    def carries(self, tool_name: str) -> ToolPresence:
        """Whether a tool of this name is already there."""
        if tool_name in self.names:
            return ToolPresence.PRESENT
        return ToolPresence.ABSENT if self.fully_read else ToolPresence.UNKNOWN


#: An entity whose tools cannot serve A2UI here whatever they are, so there is
#: nothing to read: a remote agent or team, whose tools run in the remote
#: deployment and could only be listed with an HTTP round trip per request.
NO_ENTITY_TOOLS = EntityTools()


def _tool_dict_name(tool: Dict[str, Any]) -> Optional[str]:
    """The name of a provider-executed tool passed as a dict.

    Two spellings arrive: the OpenAI nesting under ``function``, and a flat
    dict. A dict that names nothing is a provider builtin identified by its
    type alone, which cannot collide with a tool added here.
    """
    nested = tool.get("function")
    name = nested.get("name") if isinstance(nested, dict) else tool.get("name")
    return name if isinstance(name, str) else None


def is_remote_entity(entity: Any) -> bool:
    """Whether this entity's tools live in another process.

    Its tools run in the remote deployment, so they cannot serve a surface
    here whatever they are, and reading them is an HTTP round trip per
    request: the attribute itself fetches the remote configuration.
    """
    from agno.agent.remote import RemoteAgent
    from agno.team.remote import RemoteTeam

    return isinstance(entity, (RemoteAgent, RemoteTeam))


def resolve_entity_tools(entity: Any) -> EntityTools:
    """Read the tools an agent or team was defined with, once.

    A team is read through its members as well as its own list. A member's
    generation tool is how that team generates, and a leader told otherwise
    loses the render channel for the run and has a second generation tool
    injected on top of the one already there. Each member is read exactly as
    the entity itself is, so a member whose tools are a callable makes the
    answer unknowable rather than absent; a remote member is not asked.

    A tools list given as a callable is resolved by the agent at run time.
    Calling it here to look inside would run the developer's code an extra
    time per request, and hand back objects the agent then never sees, so it
    is reported as unread instead.
    """
    return _resolve_entity_tools(entity, {id(entity)})


def _resolve_entity_tools(entity: Any, seen: Set[int]) -> EntityTools:
    """One entity's own tools, plus what its members add to the answer.

    ``seen`` is what keeps a team listed among its own members, however
    indirectly, from being walked forever.
    """
    reading = _resolve_own_tools(entity)
    members = getattr(entity, "members", None)
    if members is None:
        return reading

    generates = reading.generation_tool_found
    members_read = isinstance(members, list)
    for member in members if isinstance(members, list) else []:
        if id(member) in seen or is_remote_entity(member):
            continue
        seen.add(id(member))
        member_tools = _resolve_entity_tools(member, seen)
        generates = generates or member_tools.generation_tool_found
        members_read = members_read and member_tools.fully_read and member_tools.members_fully_read
    return replace(reading, generation_tool_found=generates, members_fully_read=members_read)


def _resolve_own_tools(entity: Any) -> EntityTools:
    tools = getattr(entity, "tools", None)
    if tools is None:
        return EntityTools()
    if not isinstance(tools, list):
        return EntityTools(fully_read=False)

    names: Set[str] = set()
    generates = False
    for tool in tools:
        if isinstance(tool, Toolkit):
            names.update(tool.functions.keys())
            generates = generates or any(
                isinstance(function, A2UIGenerationFunction) for function in tool.functions.values()
            )
        elif isinstance(tool, Function):
            names.add(tool.name)
            generates = generates or isinstance(tool, A2UIGenerationFunction)
        elif isinstance(tool, dict) or callable(tool):
            # A dict is a tool the provider runs and a bare callable is one
            # Agno wraps; from here both are just a name that is taken.
            name = _tool_dict_name(tool) if isinstance(tool, dict) else getattr(tool, "__name__", None)
            if isinstance(name, str):
                names.add(name)
    return EntityTools(names=frozenset(names), generation_tool_found=generates)


class A2UIConfig(TypedDict, total=False):
    """Backend A2UI settings for an AG-UI interface.

    ``inject_a2ui_tool`` opts a backend in when the client does not ask. An
    explicit ``injectA2UITool: false`` from the client still wins, so a client
    can always turn generation off for a run.

    Declared here rather than beside the generation code so that the interface
    can name the type it accepts without importing the toolkit.
    """

    inject_a2ui_tool: Optional[Union[bool, str]]
    tool_name: Optional[str]
    tool_description: Optional[str]
    default_surface_id: Optional[str]
    default_catalog_id: Optional[str]
    catalog: Optional[Dict[str, Any]]
    guidelines: Optional["A2UIGuidelines"]
    recovery: Optional[Dict[str, Any]]
    on_a2ui_attempt: Optional[Any]
    tool_choice: Optional[Union[str, Dict[str, Any]]]
    subagent_timeout: Optional[float]


#: Every setting ``a2ui=`` accepts, read off the type so the two cannot drift.
A2UI_CONFIG_KEYS: FrozenSet[str] = frozenset(A2UIConfig.__annotations__)


def validate_a2ui_config(config: Optional[Mapping[str, Any]]) -> Optional[A2UIConfig]:
    """Refuse a setting that would otherwise be ignored.

    ``A2UIConfig`` is a TypedDict, so a misspelled key is caught wherever the
    annotation is in scope and nowhere at all once a plain dict has crossed a
    boundary. Every one of these settings turns something on or changes what it
    does, so ignoring one leaves the feature off with the configuration
    apparently in place, which is indistinguishable from the feature not
    working.
    """
    if config is None:
        return None
    if not isinstance(config, Mapping):
        raise ValueError(f"A2UI settings must be a mapping of A2UIConfig keys, not {type(config).__name__}")

    known = sorted(A2UI_CONFIG_KEYS)
    unknown = []
    for key in config:
        if key in A2UI_CONFIG_KEYS:
            continue
        nearest = get_close_matches(str(key), known, n=1)
        unknown.append(f"{key!r}{f' (did you mean {nearest[0]!r}?)' if nearest else ''}")
    if unknown:
        raise ValueError(f"Unknown A2UI setting(s): {', '.join(unknown)}. Valid settings are: {', '.join(known)}")

    return cast("A2UIConfig", dict(config))


#: How a stringified boolean reaches here from a client or a config file that
#: has no boolean of its own to send.
_NO_SPELLINGS = frozenset({"false", "0", "no", "off"})
_YES_SPELLINGS = frozenset({"true", "1", "yes", "on"})


def _as_injection_request(value: Any, setting: str) -> Optional[Union[bool, str]]:
    """One asker's answer: True, False, a render tool name, or nothing said.

    A truthy string names the render tool the client injected, which is why a
    stringified ``"false"`` cannot be left as one: it would turn generation on
    and take away a client tool called ``"false"``.
    """
    if value is None or isinstance(value, bool):
        return value
    if not value:
        # Present and false: a client with no boolean of its own to send says
        # no with a 0, and the opt-out is a promise. Discarded as unreadable
        # instead, a backend opt-in would apply and the refusal would be gone.
        return False
    if isinstance(value, str):
        spelling = value.strip().lower()
        if spelling in _NO_SPELLINGS:
            return False
        if spelling in _YES_SPELLINGS:
            return True
        if spelling:
            return value
    log_warning(f"Ignoring {setting}={value!r}: expected a boolean, or the name of the render tool to replace")
    return None


def requested_a2ui_injection(forwarded_props: Any, config: Optional[Mapping[str, Any]]) -> Union[bool, str]:
    """What this run was asked to do about injecting the generation tool.

    False for no, True for yes, and a tool name for a client that named the
    render tool it wants replaced. The client is asked first: a backend opt-in
    applies only where the client said nothing, and an explicit refusal from
    the client is never overridden.
    """
    forwarded = forwarded_props if isinstance(forwarded_props, Mapping) else {}
    requested = _as_injection_request(forwarded.get("injectA2UITool"), "injectA2UITool")
    if requested is None:
        requested = _as_injection_request((config or {}).get("inject_a2ui_tool"), "inject_a2ui_tool")
    return False if requested is None else requested
