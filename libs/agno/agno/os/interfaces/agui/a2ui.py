"""A2UI surface generation for Agno agents served over AG-UI.

A2UI lets an agent generate its own interface: instead of returning prose, a
tool returns a declarative component tree the AG-UI client renders. Generation
is delegated to a subagent, one ``render_a2ui`` turn on the agent's own model,
and only a tree that passes validation becomes the tool result. Every attempt
streams to the client while it is being written, so what keeps a rejected tree
off the screen is the client's own paint gate, which applies the same
validation.

``ag-ui-a2ui-toolkit`` owns everything framework-agnostic: the operation
builders, prompt assembly, the history walk that finds a surface to edit, the
operations envelope, semantic validation, and the validate/retry recovery loop.
This module owns only the Agno-specific glue.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import threading
import time
import uuid
from inspect import currentframe
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Set, Tuple, TypedDict, Union

from agno.os.interfaces.agui.a2ui_stream import (
    NO_ENTITY_TOOLS,
    A2UIConfig,
    A2UIGenerationFunction,
    A2UIRenderStream,
    A2UIRun,
    ToolPresence,
    current_a2ui_run,
    is_remote_entity,
    requested_a2ui_injection,
    resolve_entity_tools,
    validate_a2ui_config,
)
from agno.run.base import RunContext
from agno.utils.log import log_debug, log_error, log_warning


def _toolkit_import_message(err: ImportError) -> str:
    """Say which way the toolkit import failed.

    Three ways, each with a different fix, and naming the wrong one sends
    someone to reinstall what they already have. The package can be absent.
    It can be installed while a package it imports in turn is not, which is an
    environment to complete rather than a version to upgrade. Or it can be
    installed and no longer provide a name this module imports, which is a
    version to upgrade. The original error is carried through for the last
    two: it names the module or the symbol that was not found.
    """
    missing = err.name if isinstance(err, ModuleNotFoundError) else None
    if (missing or "").split(".")[0] == "ag_ui_a2ui_toolkit":
        return "`ag_ui_a2ui_toolkit` not installed. Please install it with `pip install -U ag-ui-a2ui-toolkit`"
    if missing:
        return (
            f"`ag_ui_a2ui_toolkit` is installed but imports `{missing}`, which this environment does not have "
            f"({err}). Please install the toolkit's dependencies with `pip install -U ag-ui-a2ui-toolkit`"
        )
    return (
        "`ag_ui_a2ui_toolkit` is installed but does not provide what the A2UI interface needs, which usually "
        f"means it is out of date ({err}). Please upgrade it with `pip install -U ag-ui-a2ui-toolkit`"
    )


try:
    from ag_ui_a2ui_toolkit import (
        A2UI_OPERATIONS_KEY,
        A2UI_SCHEMA_CONTEXT_DESCRIPTION,
        BASIC_CATALOG_ID,
        GENERATE_A2UI_ARG_DESCRIPTIONS,
        GENERATE_A2UI_TOOL_NAME,
        RENDER_A2UI_TOOL_DEF,
        A2UIGuidelines,
        A2UIToolParams,
        build_a2ui_envelope,
        prepare_a2ui_request,
        resolve_a2ui_catalog,
        resolve_a2ui_tool_params,
        run_a2ui_generation_with_recovery,
        split_a2ui_schema_context,
        wrap_error_envelope,
    )
except ImportError as e:
    raise ImportError(_toolkit_import_message(e)) from e

__all__ = [
    # Wiring generation, by hand or per request.
    "get_a2ui_tools",
    "prepare_a2ui_run",
    "A2UIAdapterOptions",
    "A2UIConfig",
    "A2UIRunPlan",
    "A2UIGenerationFunction",
    "A2UIRun",
    "A2UIGuidelines",
    "A2UIToolParams",
    "A2UIRenderAttempt",
    "A2UIRenderArgumentsError",
    # Names, defaults and keys a caller configures or recognizes a run by.
    "A2UI_OPERATIONS_KEY",
    "A2UI_SCHEMA_CONTEXT_DESCRIPTION",
    "BASIC_CATALOG_ID",
    "GENERATE_A2UI_TOOL_NAME",
    "RENDER_A2UI_TOOL_NAME",
    "OPENAI_RENDER_TOOL_CHOICE",
    "DEFAULT_RENDER_TOOL_CHOICE",
    "DEFAULT_RENDER_SUBAGENT_TIMEOUT",
    # The glue a custom wiring or another adapter reuses.
    "agui_state_from_dependencies",
    "build_agui_state",
    "classify_a2ui_subagent_error",
    "forwarded_a2ui_catalog",
    "render_guide_description",
    "stream_render_subagent",
    "strip_host_system_messages",
    "strip_in_flight_tool_call",
]

#: Name of the inner render tool the generation subagent is asked to call.
RENDER_A2UI_TOOL_NAME: str = RENDER_A2UI_TOOL_DEF["function"]["name"]

#: Tool choice for the render subagent. Nothing is forced by default. Agno
#: hands ``tool_choice`` to each provider unchanged rather than normalizing it,
#: and no spelling is accepted everywhere: the OpenAI function shape reaches
#: Gemini's ``function_calling_config.mode``, where pydantic rejects it and
#: every attempt fails, while Anthropic drops ``tool_choice`` entirely. Forcing
#: is only a reliability measure, since a subagent that answers with prose
#: instead of a tool call is already recorded as a failed attempt and retried,
#: so a default that breaks a provider outright buys nothing. Force it per
#: provider with ``A2UIAdapterOptions["tool_choice"]`` or
#: ``A2UIConfig["tool_choice"]``.
DEFAULT_RENDER_TOOL_CHOICE: Optional[Union[str, Dict[str, Any]]] = None

#: The OpenAI forced-function shape, ready to pass as ``tool_choice`` for an
#: OpenAI-compatible provider.
OPENAI_RENDER_TOOL_CHOICE: Dict[str, Any] = {
    "type": "function",
    "function": {"name": RENDER_A2UI_TOOL_NAME},
}

#: How long one render turn may take before it is given up on and recorded as
#: a failed attempt. Generous, because a large surface on a slow provider is a
#: legitimately long call; bounded, because a provider that never answers would
#: otherwise hold the tool call, and the client's whole run, open forever. It
#: bounds one turn, so a generation that retries can take a multiple of it.
#: Override per tool with ``A2UIAdapterOptions["subagent_timeout"]``, or
#: ``None`` for no bound at all.
DEFAULT_RENDER_SUBAGENT_TIMEOUT: Optional[float] = 180.0

#: How often the thread blocked on a render turn wakes to check whether the
#: caller is still there. Sets how quickly a disconnect is noticed mid-call.
_DISCONNECT_POLL_SECONDS = 0.1

#: This module's own source file, matched against the frame an exception was
#: raised in to tell a bug here from a failure the model layer or the provider
#: SDK produced.
_THIS_MODULE_FILE = __file__


class A2UIAdapterOptions(TypedDict, total=False):
    """Agno-side wiring that the shared ``A2UIToolParams`` cannot express.

    ``A2UIToolParams`` is owned by the toolkit and is identical across every
    framework adapter. Anything Agno-specific belongs here instead.
    """

    tool_choice: Optional[Union[str, Dict[str, Any]]]
    subagent_timeout: Optional[float]


class A2UIRenderArgumentsError(ValueError):
    """A render call whose arguments cannot be validated or committed.

    Raised rather than returned as an empty mapping so the reason travels with
    the failure. The shared recovery loop cannot tell an empty mapping from a
    missing one, and reports both as a sub-agent that never called the render
    tool, which is the only account of the failure the model and the client
    get. Raised, it is recorded as this attempt's cause instead.
    """


#: The classes this module raises on purpose to end one attempt. They come
#: from its own frames and are still worth another try, so the origin rule
#: below must not read them as bugs: a render call whose arguments cannot be
#: used, and a render turn that outran its deadline.
_A2UI_ATTEMPT_FAILURES: Tuple[type, ...] = (A2UIRenderArgumentsError, TimeoutError)

#: How an exception carrying no traceback is read, since it says nothing about
#: where it came from. These are the classes a mistake in this module produces:
#: reading a provider delta shape that is not there (``AttributeError``,
#: ``KeyError``, ``IndexError``), calling something the wrong way
#: (``TypeError``), a missing name or optional dependency (``NameError``,
#: ``ImportError``), or a broken invariant (``AssertionError``). The model
#: layer and the provider SDK raise every one of them too, which is why an
#: exception that does carry a traceback is judged by its origin instead.
_A2UI_ADAPTER_BUG_ERRORS: Tuple[type, ...] = (
    TypeError,
    NameError,
    AttributeError,
    KeyError,
    IndexError,
    ImportError,
    AssertionError,
)


def _is_a2ui_cancellation(err: BaseException) -> bool:
    """Whether ``err`` is a cancellation, whichever package's class it arrives as.

    The recovery loop runs on a thread and waits on a ``concurrent.futures``
    future, so cancelling the wait raises that package's own
    ``CancelledError``. It is a plain ``Exception`` and no relation of
    ``asyncio.CancelledError``, so recognizing only asyncio's reads a
    cancelled render call as a model failure and retries it after the caller
    has already gone.
    """
    return isinstance(err, (asyncio.CancelledError, concurrent.futures.CancelledError))


def _raised_in_this_module(err: BaseException) -> Optional[bool]:
    """Whether ``err`` was raised by this module's own code, or ``None`` if unknown.

    The innermost frame of a traceback is the raise site: every frame the
    exception travels through on the way out is prepended as it unwinds, and
    the future the recovery thread waits on re-raises the original object with
    its traceback intact. So the deepest frame still names where the failure
    began, however many layers it crossed to get here.

    ``None`` when there is no traceback to read, which is every exception that
    was constructed rather than raised.
    """
    tb = err.__traceback__
    if tb is None:
        return None
    while tb.tb_next is not None:
        tb = tb.tb_next
    return tb.tb_frame.f_code.co_filename == _THIS_MODULE_FILE


def classify_a2ui_subagent_error(err: BaseException) -> str:
    """Classify a subagent failure as ``"rethrow"`` or ``"recoverable"``.

    ``"rethrow"`` unwinds the tool call without consuming retries. Two kinds of
    failure earn it: cancellation, where retrying would defeat the cancel and
    spend more tokens; and this module's own mistakes, which must surface
    loudly instead of masquerading as a model that produced a bad surface.
    Everything else is a genuine model or transport failure the recovery loop
    should record as a failed attempt.

    Which of the two a failure is cannot be read off its class. ``KeyError``,
    ``AttributeError`` and friends arise as readily inside the model layer and
    the provider SDK as they do here, and killing a run over a provider-side
    one costs the caller every remaining attempt as well. So the question
    asked is where the exception was raised, not what it is called.
    """
    if _is_a2ui_cancellation(err):
        return "rethrow"
    # SystemExit and KeyboardInterrupt signal shutdown; further attempts would
    # fire model calls during interpreter teardown.
    if not isinstance(err, Exception):
        return "rethrow"
    if isinstance(err, _A2UI_ATTEMPT_FAILURES):
        return "recoverable"
    raised_here = _raised_in_this_module(err)
    if raised_here is None:
        return "rethrow" if isinstance(err, _A2UI_ADAPTER_BUG_ERRORS) else "recoverable"
    return "rethrow" if raised_here else "recoverable"


def _read_tool_call_delta(entry: Any) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[int]]:
    """Read ``(tool_name, argument_fragment, call_id, index)`` from one delta.

    Providers disagree on the shape. OpenAI-compatible models stream objects
    where only the first frame carries the tool name and later frames carry
    argument fragments; Anthropic and Gemini emit a single dict carrying the
    whole call. Both are read the same way here, and any part may be absent.
    """
    if isinstance(entry, dict):
        function: Any = entry.get("function") or {}
        call_id = entry.get("id")
        index = entry.get("index")
    else:
        function = getattr(entry, "function", None)
        call_id = getattr(entry, "id", None)
        index = getattr(entry, "index", None)

    if isinstance(function, dict):
        return function.get("name"), function.get("arguments"), call_id, index
    return getattr(function, "name", None), getattr(function, "arguments", None), call_id, index


#: How one delta names the tool call it belongs to: every dimension it carries,
#: as ``(dimension, value)`` pairs, and nothing for the ones it omits.
_DeltaKey = Tuple[Tuple[str, Any], ...]


def _delta_call_key(call_id: Optional[str], index: Optional[int]) -> _DeltaKey:
    """Every dimension one delta names its tool call by.

    Providers disagree about which dimension they stamp where.
    OpenAI-compatible streams put the id on the opening frame and the index on
    all of them; others do the mirror image, an id on the opener and an index
    on the continuations; some carry neither. Preferring one dimension over the
    other reads every continuation frame of one of those families as a
    different call and drops the whole surface, so a frame is keyed by what it
    actually carries and calls are matched dimension by dimension.
    """
    dimensions: List[Tuple[str, Any]] = []
    if call_id:
        dimensions.append(("id", call_id))
    if index is not None:
        dimensions.append(("index", index))
    return tuple(dimensions)


def _key_conflicts(known: Dict[str, Any], key: _DeltaKey) -> bool:
    """Whether a frame names a dimension differently from what is known of a call.

    A dimension the frame omits says nothing about it and so cannot conflict,
    which is what lets a continuation frame carrying only an index continue a
    call that opened carrying only an id.
    """
    return any(dimension in known and known[dimension] != value for dimension, value in key)


class _PartialToolNames:
    """Tool names still arriving in fragments, one per call being named.

    Matched dimension by dimension like the call itself, so a provider that
    names one frame by id and the next by index accumulates one name rather
    than two halves neither of which is recognizable.
    """

    def __init__(self) -> None:
        self._entries: List[Tuple[Dict[str, Any], str]] = []

    def _find(self, key: _DeltaKey) -> Optional[int]:
        for position, (known, _) in enumerate(self._entries):
            if not _key_conflicts(known, key):
                return position
        return None

    def so_far(self, key: _DeltaKey) -> str:
        found = self._find(key)
        return "" if found is None else self._entries[found][1]

    def remember(self, key: _DeltaKey, named: str) -> None:
        found = self._find(key)
        if found is None:
            self._entries.append((dict(key), named))
            return
        known = self._entries[found][0]
        known.update(key)
        self._entries[found] = (known, named)

    def forget(self, key: _DeltaKey) -> None:
        found = self._find(key)
        if found is not None:
            self._entries.pop(found)


def strip_in_flight_tool_call(messages: List[Any], tool_name: str) -> List[Any]:
    """Drop the trailing assistant turn that is calling ``tool_name`` right now.

    When the model invokes the generation tool, that assistant turn is the last
    message and has no result yet. The subagent is not offered that tool, so
    handing it an unanswered call is malformed input for providers that check
    the pairing. Only a trailing match is stripped, so a normal user turn at the
    tail survives.
    """
    if not messages:
        return []

    last = messages[-1]
    role = last.get("role") if isinstance(last, dict) else getattr(last, "role", None)
    if role != "assistant":
        return list(messages)

    tool_calls = last.get("tool_calls") if isinstance(last, dict) else getattr(last, "tool_calls", None)
    for call in tool_calls or []:
        name = _read_tool_call_delta(call)[0]
        if name == tool_name:
            return list(messages[:-1])
    return list(messages)


def _agui_context_entries(context: List[Any]) -> List[Dict[str, Any]]:
    """Forwarded context entries as the shared toolkit needs to read them.

    A served run forwards these as request models, and the toolkit's catalog
    lookup passes over every entry that is not a dict. Left as models, the
    catalog it finds is none, and a surface is bound to the basic catalog
    rather than the one the client registered and can draw.
    """
    entries: List[Dict[str, Any]] = []
    for entry in context:
        if isinstance(entry, dict):
            entries.append(entry)
        else:
            entries.append({"description": getattr(entry, "description", None), "value": getattr(entry, "value", None)})
    return entries


def build_agui_state(schema: Any, context: List[Any]) -> Dict[str, Any]:
    """Assemble the run state the shared toolkit reads the catalog and context from.

    The catalog arrives already parsed, so it is rendered back as JSON: left as
    a dict, the subagent prompt would carry a Python repr of it instead.
    """
    ag_ui: Dict[str, Any] = {"context": _agui_context_entries(context)}
    if schema is not None:
        ag_ui["a2ui_schema"] = json.dumps(schema) if isinstance(schema, (dict, list)) else schema
    return {"ag-ui": ag_ui}


def agui_state_from_dependencies(dependencies: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Rebuild the ``state["ag-ui"]`` shape the toolkit reads from run dependencies.

    The AG-UI router turns every ``RunAgentInput.context`` entry into a
    dependency keyed by the entry's description, which puts the A2UI component
    schema at a known key. Split it back out from the ordinary context entries:
    the toolkit renders the schema as an available-components block and the rest
    as plain context.
    """
    context: List[Dict[str, Any]] = []
    schema: Any = None

    for description, value in (dependencies or {}).items():
        if description == A2UI_SCHEMA_CONTEXT_DESCRIPTION:
            schema = value
        else:
            context.append({"description": description, "value": value})

    return build_agui_state(schema, context)


def _structural_gate_only(reason: str) -> Optional[Dict[str, Any]]:
    """Report that the retry gate just lost the client's rule, and why.

    Said out loud every time, because the gate carrying on with fewer checks
    looks from the outside exactly like the gate that is checking everything.
    """
    log_warning(
        f"A2UI component schema was forwarded but {reason}, so generated surfaces are checked for structure "
        "only and a component the client cannot draw will reach it unchallenged."
    )
    return None


def _flattened_component_schema(entry: Any) -> Optional[Dict[str, Any]]:
    """One component's schema, with any ``allOf`` composition folded into it.

    The client composes each component against a shared component base, so what
    the component takes and what it requires arrive nested inside ``allOf``
    members. The shared validator reads ``properties`` and ``required`` off the
    top of the entry, so left nested every component reads as one that requires
    nothing and declares no property: catalog membership would still be checked
    and required properties never would. Members are merged in the order they
    are composed, which is the order the client's own resolution follows.
    """
    if not isinstance(entry, dict):
        return None

    schema: Dict[str, Any] = {}
    properties: Dict[str, Any] = {}
    required: List[str] = []

    def absorb(member: Any) -> None:
        if not isinstance(member, dict):
            return
        for key, value in member.items():
            if key == "allOf":
                for nested in value if isinstance(value, list) else []:
                    absorb(nested)
            elif key == "properties" and isinstance(value, dict):
                properties.update(value)
            elif key == "required" and isinstance(value, list):
                required.extend(name for name in value if isinstance(name, str) and name not in required)
            else:
                schema.setdefault(key, value)

    absorb(entry)
    if properties:
        schema["properties"] = properties
    if required:
        schema["required"] = required
    return schema


def forwarded_a2ui_catalog(state: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The catalog the client registered, in the shape the shared validator reads.

    The two ends of this feature have to apply one rule. The client's renderer
    validates a tree against the catalog it registered, so it also refuses a
    component that catalog does not define and one that is missing a property
    that catalog requires. The server's retry gate is handed a catalog only
    when the host hard-coded one, so without this a tree that is structurally
    fine but names components the client cannot draw passes validation, is
    committed as the tool result, and is then silently refused by the browser:
    no attempt is left to heal it and nobody is told.

    The wire sends ``{"catalogId": ..., "components": {<name>: <schema>}}``,
    each schema composed with ``allOf`` against a shared component base, and
    the validator wants component schemas keyed by name with their properties
    and required lists at the top. Only that keyed shape yields a catalog,
    which is the same line the client's own middleware draws: it builds no
    validation catalog from the legacy array forms either and falls back to
    structural checks, so reading an array here would leave this gate the
    stricter of the two.

    Returns ``None`` when the run forwarded no schema, or forwarded one that
    names no components: the structural gate alone is what this had before, and
    it is a better answer than declining to generate at all.
    """
    ag_ui = state.get("ag-ui") if isinstance(state, dict) else None
    raw = ag_ui.get("a2ui_schema") if isinstance(ag_ui, dict) else None
    if not raw:
        return None

    parsed: Any = raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return _structural_gate_only("it is not valid JSON")

    components = parsed.get("components") if isinstance(parsed, dict) else None
    if not isinstance(components, dict) or not components:
        return _structural_gate_only("it does not key component schemas by name")

    by_name: Dict[str, Any] = {}
    for name, entry in components.items():
        schema = _flattened_component_schema(entry)
        if isinstance(name, str) and name and schema is not None:
            by_name[name] = schema

    if not by_name:
        return _structural_gate_only("none of its component schemas can be read")
    return {"components": by_name}


class A2UIRenderAttempt(NamedTuple):
    """The identity of one render attempt: what it is called, and what it names.

    Decided once, before the attempt emits anything, and read by both sites
    that would otherwise each choose for themselves: the fragments a client
    paints the surface from, and the envelope committed as the tool's result.
    Anything either site decides on its own can disagree with the other, and
    every such disagreement looks the same from the server, which logs a
    generated surface and a client that shows none.

    A retry gets a new identity. An attempt that reuses a rejected attempt's
    wire id has its arguments appended to the buffer the client is still
    holding for that id, so the two attempts parse as one malformed object and
    the healed surface never paints.
    """

    #: The tool-call id every event of this attempt is emitted under. Host
    #: chosen rather than the provider's, which is reused across attempts.
    call_id: str
    #: The surface this attempt commits to, or ``None`` when the model names
    #: it, which is every create.
    surface_id: Optional[str] = None
    #: The catalog the surface is resolved in. Never the model's to choose.
    catalog_id: Optional[str] = None

    @classmethod
    def new(cls, surface_id: Optional[str] = None, catalog_id: Optional[str] = None) -> "A2UIRenderAttempt":
        """Mint an identity for one attempt, with a wire id belonging to it alone."""
        return cls(call_id=f"a2ui-render-{uuid.uuid4().hex[:8]}", surface_id=surface_id, catalog_id=catalog_id)

    @property
    def host_fields(self) -> Dict[str, str]:
        """The argument members the host owns, in the order they are written."""
        fields: Dict[str, str] = {}
        if self.surface_id:
            fields["surfaceId"] = self.surface_id
        if self.catalog_id:
            fields["catalogId"] = self.catalog_id
        return fields

    def confirm(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """The arguments of an attempt that streamed under this identity, or a refusal.

        On an update every id is this identity's and is imposed on the stream
        and the envelope alike, so the two cannot part. On a create the model
        names the surface and the client paints the name it was sent, while the
        envelope commits that name only when it is a non-empty string and
        narrows anything else to the configured default. Left to narrow, such
        an attempt paints one surface and commits another: the skeleton the
        client mounted is never filled, and the surface that was committed was
        never painted. The attempt is ended here instead, which costs a retry
        and tells the model what to name.

        A name the model never wrote is left alone: nothing was painted under
        a competing id, so the default disagrees with nothing.
        """
        if self.surface_id is not None or "surfaceId" not in arguments:
            return arguments
        named = arguments["surfaceId"]
        if isinstance(named, str) and named:
            return arguments
        raise A2UIRenderArgumentsError(
            f"the render call named surfaceId {named!r}, which cannot be committed as written: name the "
            "surface with a non-empty string"
        )


class _EmittedRenderArguments:
    """One render call's argument stream, rewritten so the host owns its ids.

    A client mounts and paints the surface from these fragments while they
    arrive, so the ids it reads have to be the ids the committed envelope will
    carry. Two things follow. The host's members are written as the object's
    first, because a surface cannot be mounted before it is named. And a
    member of the model's own under a host-owned name is dropped, because a
    JSON parser keeps the last of two identical keys: left in, the id the
    model guessed at would take the surface back at the end of the stream.

    Separators between the remaining members are rewritten with them, since
    their order changed. Arguments that own no field, and arguments that are
    not a JSON object and so have nowhere to carry an id, go out exactly as
    the model wrote them.

    Every way out of the object closes it. A client reads these fragments with
    an incremental parser, so a member emitted without the separator or the
    colon that was swallowed for it paints no surface at all, and this exists
    to keep unparseable arguments off the wire rather than to make new ones.
    Whatever follows the close belonged to a member that cannot be placed in an
    object already ended, so it is dropped.
    """

    def __init__(self, host_fields: Dict[str, str]) -> None:
        self._host_fields = host_fields
        # Two terminal phases: "verbatim" passes the model's own bytes through
        # untouched, "done" emits nothing more.
        self._phase = "before-object" if host_fields else "verbatim"
        self._key = ""
        self._depth = 0
        self._in_string = False
        self._escaped = False
        self._wrote_member = False

    def feed(self, fragment: str) -> str:
        """What to emit for one fragment of the model's arguments."""
        if self._phase == "verbatim":
            return fragment
        if self._phase == "done":
            return ""
        out: List[str] = []
        for char in fragment:
            self._consume(char, out)
        return "".join(out)

    def _finish(self, out: List[str]) -> None:
        """Close the object this opened, and rewrite nothing further."""
        out.append("}")
        self._phase = "done"

    def _consume(self, char: str, out: List[str]) -> None:
        if self._phase == "done":
            return
        if self._phase == "verbatim":
            out.append(char)
        elif self._phase == "before-object":
            self._before_object(char, out)
        elif self._phase == "member-start":
            self._member_start(char, out)
        elif self._phase == "key":
            self._key_char(char)
        elif self._phase == "after-key":
            self._after_key(char, out)
        else:
            self._value_char(char, out, keep=self._phase == "value")

    def _before_object(self, char: str, out: List[str]) -> None:
        if char.isspace():
            out.append(char)
            return
        if char != "{":
            self._phase = "verbatim"
            out.append(char)
            return
        members = ", ".join(f'"{name}": {json.dumps(value)}' for name, value in self._host_fields.items())
        out.append("{" + members)
        self._wrote_member = bool(members)
        self._phase = "member-start"

    def _member_start(self, char: str, out: List[str]) -> None:
        if char.isspace() or char == ",":
            return
        if char == '"':
            self._key = '"'
            self._phase = "key"
            return
        # The object ends, or the model wrote something no object may contain,
        # which cannot be emitted as a member of one either way.
        self._finish(out)

    def _key_char(self, char: str) -> None:
        self._key += char
        if self._escaped:
            self._escaped = False
        elif char == "\\":
            self._escaped = True
        elif char == '"':
            self._phase = "after-key"

    def _after_key(self, char: str, out: List[str]) -> None:
        if char.isspace():
            return
        if char != ":":
            # A key with no value is no member, and emitting it would leave the
            # host's own members separated from it by nothing at all.
            self._finish(out)
            return
        try:
            owned = json.loads(self._key) in self._host_fields
        except json.JSONDecodeError:
            owned = False
        self._depth = 0
        if owned:
            self._phase = "skipped-value"
            return
        if self._wrote_member:
            out.append(", ")
        out.append(self._key + ":")
        self._wrote_member = True
        self._phase = "value"

    def _value_char(self, char: str, out: List[str], keep: bool) -> None:
        if self._in_string:
            if keep:
                out.append(char)
            if self._escaped:
                self._escaped = False
            elif char == "\\":
                self._escaped = True
            elif char == '"':
                self._in_string = False
            return
        if char == '"':
            self._in_string = True
        elif char in "{[":
            self._depth += 1
        elif char in "}]" and self._depth > 0:
            self._depth -= 1
        elif self._depth == 0 and char == ",":
            self._phase = "member-start"
            return
        elif self._depth == 0 and char == "}":
            self._finish(out)
            return
        if keep:
            out.append(char)


def strip_host_system_messages(messages: List[Any]) -> List[Any]:
    """Drop the host agent's instruction turns from the subagent's input.

    The subagent runs under its own render prompt. The outer agent's system
    message rides along in the run history, and handing both over sets two
    instructions against each other: the render prompt says to call the render
    tool, the host persona says to answer as that persona, and the persona
    tends to win. ``developer`` is stripped with ``system`` because providers
    that accept it treat it the same way.
    """
    kept: List[Any] = []
    for message in messages:
        role = message.get("role") if isinstance(message, dict) else getattr(message, "role", None)
        if role in ("system", "developer"):
            continue
        kept.append(message)
    return kept


class _RenderCall:
    """The one render call a turn may produce, and every transition it allows.

    Three phases and no more. ``pending`` until the render tool has been named
    in full, ``open`` while its arguments accumulate and stream, ``closed``
    once it has been ended. ``closed`` is terminal: a turn commits one
    surface, so a second render call would paint one with nothing behind it,
    and reopening the call would append to a buffer the client already holds.

    Every event goes out under the attempt's own id rather than the
    provider's, which providers reuse across attempts.
    """

    def __init__(self, attempt: A2UIRenderAttempt, emit: Callable[[Dict[str, Any]], None]) -> None:
        self._attempt = attempt
        self._emit = emit
        self._phase = "pending"
        #: Every dimension this call has been named by so far, learned as its
        #: frames arrive: a provider that stamps the id on the opening frame
        #: and the index on the continuations tells it the index only once the
        #: first continuation is here.
        self._named_by: Dict[str, Any] = {}
        self._emitted = _EmittedRenderArguments(attempt.host_fields)
        #: Exactly what the model wrote, which is what validation reads.
        self.arguments = ""
        #: Whether a render call was ever seen, which is a different fact from
        #: whether one is open: conflating them throws away a surface that
        #: streamed in full just because the provider named another tool after
        #: it.
        self.seen = False

    def start(self, key: _DeltaKey) -> bool:
        """Open the turn's render call, or refuse a later one."""
        if self._phase != "pending":
            return False
        self._phase = "open"
        self._named_by = dict(key)
        self.seen = True
        self._emit(
            {
                "kind": "start",
                "tool_call_id": self._attempt.call_id,
                "tool_call_name": RENDER_A2UI_TOOL_NAME,
            }
        )
        return True

    def accepts(self, key: _DeltaKey) -> bool:
        """Whether a frame keyed this way belongs to the call in progress.

        Only a frame that names a dimension differently from this call is
        another call's. A dimension it omits says nothing, which is how
        providers stream argument fragments after the opening frame, how
        providers such as ollama repeat the tool name on every frame of a
        single call, and how a stream keyed by id on its opener and by index
        thereafter stays one call.
        """
        return self._phase == "open" and not _key_conflicts(self._named_by, key)

    def absorb(self, key: _DeltaKey) -> None:
        """Learn the dimensions a frame of this call names it by."""
        self._named_by.update(key)

    def dropped_from(self, key: _DeltaKey) -> bool:
        """Whether a fragment arriving now was part of this call, already closed.

        What separates a fragment of the committed surface arriving too late
        to be part of it from a fragment of some other call the provider
        happened to echo. A frame that names no call at all is this one's:
        there is no other call for it to belong to, and the surface it was
        meant to finish is the one that truncated.
        """
        return self._phase == "closed" and not _key_conflicts(self._named_by, key)

    def is_identified_by(self, key: _DeltaKey) -> bool:
        """Whether a frame names the call in progress, rather than continuing it.

        Only such a frame can take the call's place, which is what separates a
        provider echoing another tool over this call from one echoing it
        beside a call it cannot name.
        """
        return self._phase == "open" and any(self._named_by.get(dimension) == value for dimension, value in key)

    def extend(self, fragment: str) -> None:
        if self._phase != "open":
            return
        self.arguments += fragment
        emitted = self._emitted.feed(fragment)
        if emitted:
            self._emit({"kind": "args", "tool_call_id": self._attempt.call_id, "delta": emitted})

    def close(self) -> None:
        if self._phase != "open":
            return
        self._phase = "closed"
        self._emit({"kind": "end", "tool_call_id": self._attempt.call_id})


def _parse_render_arguments(raw: str) -> Dict[str, Any]:
    """Read what a render call streamed, or say why it cannot be used.

    Every shape refused here costs one attempt and is retried rather than
    committing an unrenderable surface, and the reason reaches the model in
    the failure envelope instead of being flattened into "did not call
    render_a2ui".
    """
    if not raw.strip():
        raise A2UIRenderArgumentsError("the render call carried no arguments")
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as err:
        raise A2UIRenderArgumentsError(f"the render arguments were not valid JSON: {err}") from err
    if not isinstance(parsed, dict):
        # The shared toolkit reads these as a mapping; a list or a scalar would
        # raise there and take the whole run down with it.
        raise A2UIRenderArgumentsError(f"the render arguments were {type(parsed).__name__}, not an object")
    if not parsed:
        raise A2UIRenderArgumentsError("the render arguments were an empty object")
    return parsed


async def stream_render_subagent(
    model: Any,
    prompt: str,
    messages: List[Any],
    tool_choice: Optional[Union[str, Dict[str, Any]]],
    push: Optional[Callable[[Dict[str, Any]], None]] = None,
    attempt: Optional[A2UIRenderAttempt] = None,
) -> Optional[Dict[str, Any]]:
    """Run one ``render_a2ui`` turn and return the arguments it produced.

    Returns ``None`` when the subagent produced no render call at all, and
    raises ``A2UIRenderArgumentsError`` when it produced one whose arguments
    cannot be used. The recovery loop records either as a failed attempt.

    ``attempt`` is the identity this turn is painted and committed under, and
    the caller decides it before the turn starts so that both can be the same.
    An attempt of its own is minted when there is none, since every emitted
    event needs an id whatever the provider does.

    This is a single model turn rather than a nested agent run. An agent loop
    would execute the bound render tool and fire a second call to continue the
    turn, and under a "render this surface" system prompt that continuation
    tends to render again instead of settling — the surface paints but the
    outer tool call never returns.

    ``push`` receives the render call's progress as it streams, so a client can
    paint the surface while it is still being written. How progressive that is
    depends on the provider: models that stream partial tool arguments give a
    fragment at a time, while a provider that hands over the whole call at once
    yields a single fragment.
    """
    from agno.models.base import MessageData
    from agno.models.message import Message

    subagent_messages = [Message(role="system", content=prompt), *strip_host_system_messages(messages)]
    assistant_message = Message(role=model.assistant_message_role)
    stream_data = MessageData()

    def emit(payload: Dict[str, Any]) -> None:
        if push is not None:
            push(payload)

    identity = attempt or A2UIRenderAttempt.new()
    call = _RenderCall(identity, emit)
    # The tool name as each call has spelled it so far, because some providers
    # stream the name itself in fragments.
    names = _PartialToolNames()
    reported: set = set()

    def report_once(reason: str, message: str, level: Callable[[str], None] = log_debug) -> None:
        """Account for one branch this turn took, the first time it takes it.

        Every branch that declines to do what the stream asked owes the
        caller an explanation, and none of them can afford to give it per
        fragment: a provider sends hundreds, and each one can take the same
        branch.
        """
        if reason in reported:
            return
        reported.add(reason)
        level(message)

    try:
        async for delta in model.aprocess_response_stream(
            messages=subagent_messages,
            assistant_message=assistant_message,
            stream_data=stream_data,
            tools=[RENDER_A2UI_TOOL_DEF],
            tool_choice=tool_choice,
        ):
            for entry in delta.tool_calls or []:
                name, fragment, call_id, index = _read_tool_call_delta(entry)
                key = _delta_call_key(call_id, index)

                if name:
                    # Empty rather than absent on continuation frames for some
                    # providers, which is why this is a truthiness test: read
                    # as a name it would start a bogus call and the real
                    # arguments would be dropped.
                    # A whole name stands on its own, so a foreign tool whose
                    # name merely begins like the render tool's cannot leave a
                    # fragment behind that spoils the next name read.
                    named = name if name == RENDER_A2UI_TOOL_NAME else names.so_far(key) + name
                    if named != RENDER_A2UI_TOOL_NAME and RENDER_A2UI_TOOL_NAME.startswith(named):
                        # A provider streaming the name in pieces. The call
                        # cannot start until the name is whole, and blaming
                        # the model for not calling the tool would be wrong.
                        names.remember(key, named)
                        report_once(
                            "partial-name",
                            f"A2UI render turn is receiving the tool name in fragments ({named!r} so far). "
                            "Nothing is emitted until it is whole.",
                        )
                        continue
                    names.forget(key)
                    if named != RENDER_A2UI_TOOL_NAME:
                        # Only one tool is offered, so this is a provider echo
                        # of some other call. It ends the render call only when
                        # it takes its place, which a frame that identifies no
                        # call cannot do; whatever streamed is kept either way.
                        report_once(
                            "foreign-name",
                            f"A2UI render turn saw a call to {named!r}, which is not the render tool and is not "
                            "offered to the sub-agent. Whatever the render call streamed is kept.",
                        )
                        if call.is_identified_by(key):
                            call.close()
                        continue
                    if call.accepts(key):
                        call.absorb(key)
                    elif not call.start(key):
                        report_once(
                            "second-render-call",
                            "A2UI render turn produced more than one render call. Keeping the first: the "
                            "client has already painted it, and only one surface is committed, so a later "
                            "call would leave a surface on screen that nothing backs.",
                            log_warning,
                        )
                        continue

                if fragment:
                    if call.accepts(key):
                        call.absorb(key)
                        call.extend(fragment)
                    elif call.dropped_from(key):
                        report_once(
                            "fragment-after-close",
                            "A2UI render call received argument fragments after it was closed. They are not "
                            "part of the committed surface, which may therefore be truncated.",
                            log_warning,
                        )
                    else:
                        report_once(
                            "foreign-fragment",
                            "A2UI render turn carried argument fragments for a call that is not the render "
                            "call, and dropped them.",
                        )
    except BaseException:
        # The provider stream died mid-call. Close the emitted call before
        # unwinding: leaving one open breaks the protocol, and the next attempt
        # would open another on top of it.
        call.close()
        raise

    call.close()

    if not call.seen:
        log_debug("A2UI render turn produced no render call, which the recovery loop records as a failed attempt.")
        return None
    return identity.confirm(_parse_render_arguments(call.arguments))


def _log_abandoned_recovery(future: "concurrent.futures.Future") -> None:
    """Report a recovery failure nobody is waiting for any more.

    Attached only once the caller has gone, and to the worker's own future
    rather than the awaitable wrapped around it: cancelling the await cancels
    that wrapper, and a cancelled wrapper never receives the worker's result at
    all, so the error this exists to report would be dropped there.
    """
    if future.cancelled():
        return
    error = future.exception()
    if error is None or _is_a2ui_cancellation(error):
        return
    log_warning(f"A2UI recovery loop failed after its caller disconnected: {type(error).__name__}: {error}")


def _start_recovery_thread(work: Callable[[], Any]) -> "concurrent.futures.Future":
    """Run the synchronous recovery loop on a thread of its own.

    Not on the loop's default executor. An attempt spends nearly all its time
    blocked on a model call, and a generation can make three, so parking one
    there holds a thread the whole process shares for as long as the provider
    takes: enough concurrent generations and nothing else in the process can
    reach the pool at all.
    """
    worker: "concurrent.futures.Future" = concurrent.futures.Future()

    def run() -> None:
        if not worker.set_running_or_notify_cancel():
            return
        try:
            worker.set_result(work())
        except BaseException as err:
            worker.set_exception(err)

    threading.Thread(target=run, name="a2ui-recovery", daemon=True).start()
    return worker


def _wait_for_a2ui_subagent(
    pending: "concurrent.futures.Future",
    abandoned: threading.Event,
    loop: asyncio.AbstractEventLoop,
    timeout: Optional[float],
) -> Optional[Dict[str, Any]]:
    """Block on one scheduled render turn without becoming unresponsive.

    The recovery loop is synchronous, so this thread has to block somewhere.
    Blocking outright would mean a disconnect is noticed only between attempts
    and a provider that never answers is waited on forever, so the wait is
    broken into polls: an abandoned run gives up at once and cancels the call,
    and a call past its deadline is cancelled and raised as a failed attempt.
    """
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        wait_for = _DISCONNECT_POLL_SECONDS
        if deadline is not None:
            wait_for = min(wait_for, max(deadline - time.monotonic(), 0.0))
        # Waiting on the future rather than ``result(timeout=...)``: a wait that
        # timed out and a ``TimeoutError`` raised by the call itself are the
        # same class, and telling them apart matters here.
        concurrent.futures.wait([pending], timeout=wait_for)
        if pending.done():
            return pending.result()
        if abandoned.is_set() or loop.is_closed():
            pending.cancel()
            raise asyncio.CancelledError("caller disconnected; abandoning A2UI generation")
        if deadline is not None and time.monotonic() >= deadline:
            pending.cancel()
            raise TimeoutError(f"A2UI render subagent did not answer within {timeout}s")


def _with_subagent_causes(envelope: str, causes: List[str]) -> str:
    """Keep why attempts really failed in the envelope the model reads.

    The shared loop only ever learns that an attempt yielded no surface, so its
    failure envelope says the sub-agent did not call the render tool. When the
    real cause was a provider or transport error, an expired key say, that
    wording is not merely vague but wrong, and it is the only account of the
    failure the model and the client get.
    """
    try:
        payload = json.loads(envelope)
    except (json.JSONDecodeError, TypeError):
        return envelope
    if not isinstance(payload, dict):
        return envelope
    payload["subagentErrors"] = causes
    return json.dumps(payload)


def _on_the_awaiting_tool_path() -> bool:
    """Whether this hook is running under the tool path that awaits the entrypoint.

    A running event loop does not answer that: a synchronous run driven from
    inside one, a notebook cell or a sync call in an async handler, still
    takes the synchronous path. Agno runs a synchronous pre-hook from both
    ``FunctionCall.execute`` and ``FunctionCall.aexecute``, so the nearer of
    the two on the stack is what says which path this call is on.

    With neither on the stack the tool is being driven by something else, and
    a running loop is then the only evidence there is.
    """
    from agno.tools.function import FunctionCall

    awaiting = FunctionCall.aexecute.__code__
    keeping = FunctionCall.execute.__code__
    frame = currentframe()
    while frame is not None:
        if frame.f_code is awaiting:
            return True
        if frame.f_code is keeping:
            return False
        frame = frame.f_back
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


def _synchronous_path_guard(tool_name: str) -> Callable[[], None]:
    """Refuse the synchronous tool path instead of handing a model a coroutine.

    Generation is asynchronous: it streams a subagent turn and waits on the
    caller's own event loop. Agno's synchronous tool path calls the entrypoint
    and keeps whatever comes back, so the call "succeeds" with a coroutine
    nobody awaited and the model is sent its repr, with only a stray "never
    awaited" warning to go on.

    A team run is what reaches here. An agent collecting its tools for a
    synchronous run refuses an async tool of its own accord, with a message
    that says as much; the team path has no such check, so the tool is called
    and its coroutine kept.

    Wired as the tool's pre-hook, which both paths run before the entrypoint.
    """

    def refuse_a_synchronous_call() -> None:
        if _on_the_awaiting_tool_path():
            return
        from agno.exceptions import AgentRunException

        message = (
            f"'{tool_name}' generates A2UI asynchronously and cannot run on Agno's synchronous tool path. "
            "Drive the agent or team with arun() or aprint_response(), or serve it over AG-UI."
        )
        log_error(message)
        raise AgentRunException(message) from None

    return refuse_a_synchronous_call


def get_a2ui_tools(params: A2UIToolParams, options: Optional[A2UIAdapterOptions] = None) -> A2UIGenerationFunction:
    """Build the A2UI generation tool for an Agno agent.

    Add the returned tool to an agent's ``tools`` and the model can generate
    interface surfaces on demand::

        from agno.os.interfaces.agui.a2ui import get_a2ui_tools

        model = OpenAIChat(id="gpt-5.6-luna")
        agent = Agent(model=model, tools=[get_a2ui_tools({"model": model})])

    Args:
        params: The shared cross-framework parameters. ``model`` is the model
            the render subagent runs on and is required; the rest are behavior
            knobs the toolkit fills with canonical defaults.
        options: Agno-specific wiring, currently the ``tool_choice`` to run
            the render subagent with.

    Returns:
        An Agno ``Function`` whose result is an A2UI operations envelope.
    """
    if params.get("model") is None:
        # Left implicit, the subagent would bind whatever default model the
        # provider supplies, so a surface would be generated by a model the
        # caller never chose.
        raise ValueError("get_a2ui_tools requires a 'model' — the Agno model the render subagent runs on.")

    recovery = params.get("recovery")
    if isinstance(recovery, dict):
        for key in recovery:
            if isinstance(key, str) and "_" in key:
                log_warning(
                    f"A2UI recovery option {key!r} is ignored: the shared toolkit reads "
                    "camelCase keys such as 'maxAttempts'."
                )

    cfg = resolve_a2ui_tool_params(params)
    # ``resolve_a2ui_tool_params`` substitutes the basic catalog when no id was
    # given, which would hide the catalog the client registered for this run.
    # Keep the caller's own choice separate so it still wins.
    caller_catalog_id = params.get("default_catalog_id")
    tool_choice = (options or {}).get("tool_choice", DEFAULT_RENDER_TOOL_CHOICE)
    subagent_timeout = (options or {}).get("subagent_timeout", DEFAULT_RENDER_SUBAGENT_TIMEOUT)
    tool_name = cfg["tool_name"]

    async def generate_a2ui(
        intent: str = "create",
        target_surface_id: Optional[str] = None,
        changes: Optional[str] = None,
        run_context: Optional[RunContext] = None,
    ) -> str:
        run = current_a2ui_run.get()
        render_stream = run.render_stream if run is not None else None

        # The agent's own history for the subagent to read.
        messages = strip_in_flight_tool_call(list(getattr(run_context, "messages", None) or []), tool_name)

        # Where to look for a surface the model asked to edit. The agent's run
        # history covers only the turn in progress, so a surface rendered in an
        # earlier turn is found in what the client sent. The run's own messages
        # come last because the search works backwards, so a surface created
        # earlier in this same turn wins.
        history: List[Any] = [*(run.messages if run is not None else []), *messages]

        state = (
            run.state
            if run is not None and run.state is not None
            else agui_state_from_dependencies(getattr(run_context, "dependencies", None))
        )

        resolved = resolve_a2ui_catalog(state)
        runtime_catalog_id = resolved[1] if resolved else None
        catalog_id = caller_catalog_id or runtime_catalog_id or cfg["default_catalog_id"]

        # The catalog the retry gate validates against. A host that hard-coded
        # one has said which components it will draw; otherwise the client's
        # own forwarded schema is the answer, so that the gate here refuses
        # what the renderer there would refuse.
        validation_catalog = cfg["catalog"] or forwarded_a2ui_catalog(state)

        prep = prepare_a2ui_request(
            intent=intent,
            target_surface_id=target_surface_id,
            changes=changes,
            messages=history,
            state=state,
            guidelines=cfg["guidelines"],
        )
        if prep.get("error"):
            # The model reads the envelope and can correct itself, but leave a
            # server-side breadcrumb so these stay countable.
            log_warning(f"A2UI request preparation failed: {prep['error']}")
            return wrap_error_envelope(prep["error"])

        # One identity per attempt, decided here and read by both the stream
        # that paints the surface and the envelope that commits it. An update
        # is committed to the surface the caller named and the catalog that
        # surface was created in, whatever the model writes; a create leaves
        # the surface id to the model, which is the only field it owns.
        prior = prep.get("prior")
        committed_surface_id = target_surface_id if prep["is_update"] else None
        committed_catalog_id = (prior or {}).get("catalogId") or catalog_id

        def next_attempt() -> A2UIRenderAttempt:
            return A2UIRenderAttempt.new(surface_id=committed_surface_id, catalog_id=committed_catalog_id)

        identity = next_attempt()

        def build_envelope(render_args: Dict[str, Any]) -> str:
            # Called with the arguments of the attempt that just produced them,
            # so ``identity`` is that attempt's.
            args = render_args if identity.surface_id is None else {**render_args, "surfaceId": identity.surface_id}
            return build_a2ui_envelope(
                args=args,
                is_update=prep["is_update"],
                target_surface_id=identity.surface_id,
                prior=prior,
                default_surface_id=cfg["default_surface_id"],
                default_catalog_id=identity.catalog_id,
            )

        loop = asyncio.get_running_loop()
        # Set when the caller goes away, so the loop stops before spending
        # another subagent call on a surface nobody will see.
        abandoned = threading.Event()
        # Written by the recovery thread and read by this one when it unwinds.
        in_flight_lock = threading.Lock()
        in_flight: Optional["concurrent.futures.Future"] = None
        # Why attempts failed, per attempt, for a failure envelope and a retry
        # prompt that would otherwise blame the model for a provider error.
        causes: Dict[int, str] = {}

        def cancel_in_flight() -> None:
            with in_flight_lock:
                pending = in_flight
            if pending is not None:
                pending.cancel()

        def invoke_subagent(prompt: str, attempt_number: int) -> Optional[Dict[str, Any]]:
            nonlocal in_flight, identity
            if abandoned.is_set() or loop.is_closed():
                raise asyncio.CancelledError("caller disconnected; abandoning A2UI generation")
            # Before anything is emitted, so nothing this attempt paints can
            # be buffered against a rejected attempt's wire id.
            identity = next_attempt()
            # The shared loop only ever learns that an attempt yielded no
            # surface, so the prompt it built for this one says the sub-agent
            # did not call the render tool. Where the attempt before actually
            # failed on a provider or transport error, or wrote arguments that
            # could not be used, that is the account this attempt needs.
            previous_cause = causes.get(attempt_number - 1)
            if previous_cause is not None:
                prompt = f"{prompt}\n\nThe previous attempt did not finish: {previous_cause}"
            # The recovery loop is synchronous, so it runs on a thread of its
            # own, but the subagent itself is scheduled back onto the request's
            # event loop. Running it on a fresh loop inside the thread instead
            # would use the model's HTTP client from a loop it was not bound to,
            # and the subagent shares its model with the agent that called it.
            pending = asyncio.run_coroutine_threadsafe(
                stream_render_subagent(
                    cfg["model"],
                    prompt,
                    messages,
                    tool_choice,
                    push=render_stream.push if render_stream is not None else None,
                    attempt=identity,
                ),
                loop,
            )
            with in_flight_lock:
                in_flight = pending
            try:
                return _wait_for_a2ui_subagent(pending, abandoned, loop, subagent_timeout)
            except BaseException as err:
                if classify_a2ui_subagent_error(err) == "rethrow":
                    raise
                cause = f"{type(err).__name__}: {err}"
                causes[attempt_number] = cause
                log_warning(f"A2UI subagent failed on attempt {attempt_number}, recording a failed attempt: {cause}")
                return None
            finally:
                with in_flight_lock:
                    in_flight = None

        worker = _start_recovery_thread(
            lambda: run_a2ui_generation_with_recovery(
                base_prompt=prep["prompt"],
                catalog=validation_catalog,
                config=cfg["recovery"],
                on_attempt=cfg["on_a2ui_attempt"],
                invoke_subagent=invoke_subagent,
                build_envelope=build_envelope,
            )
        )

        try:
            result = await asyncio.wrap_future(worker, loop=loop)
        except BaseException:
            abandoned.set()
            cancel_in_flight()
            if not worker.done():
                # Still running, so nobody is left to see how it ends. An
                # already finished worker needs no such report: its outcome is
                # the exception being raised here.
                worker.add_done_callback(_log_abandoned_recovery)
            raise

        log_debug(f"A2UI generation finished after {len(result['attempts'])} attempt(s), ok={result['ok']}")
        if not result["ok"] and causes:
            return _with_subagent_causes(result["envelope"], [causes[at] for at in sorted(causes)])
        return result["envelope"]

    return A2UIGenerationFunction(
        name=tool_name,
        description=cfg["tool_description"],
        # This tool writes its own schema, in which two of the three arguments
        # describe an edit and only ``intent`` is asked of every call. Strict
        # mode cannot say that: it requires every property. Declared not
        # strict, the schema the provider receives is the one written here,
        # and the provider is promised no adherence this schema does not ask
        # for.
        strict=False,
        parameters={
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": ["create", "update"],
                    "description": GENERATE_A2UI_ARG_DESCRIPTIONS["intent"],
                },
                "target_surface_id": {
                    "type": "string",
                    "description": GENERATE_A2UI_ARG_DESCRIPTIONS["target_surface_id"],
                },
                "changes": {
                    "type": "string",
                    "description": GENERATE_A2UI_ARG_DESCRIPTIONS["changes"],
                },
            },
            # Stated, because a provider reads a missing ``required`` as every
            # property being required, and the other two describe an edit:
            # demanding them would make creating a first surface impossible.
            "required": ["intent"],
        },
        entrypoint=generate_a2ui,
        skip_entrypoint_processing=True,
        pre_hook=_synchronous_path_guard(tool_name),
    )


class A2UIRunPlan(TypedDict):
    """What the router needs to serve one request's A2UI arrangements."""

    #: Context to forward to the agent, with the component catalog taken out
    #: when this run's generation happens server-side and reads it from state.
    context: List[Any]
    #: The generation tool to add for this run, if one is being injected.
    tool: Optional[A2UIGenerationFunction]
    #: Client tools to discard, namely the render tool this replaces.
    drop_tool_names: List[str]
    #: The per-request inputs the generation tool reads.
    run: A2UIRun


def render_guide_description(tool_name: str) -> str:
    """The context entry the A2UI middleware attaches to explain the render tool.

    Matched by exact text against what the middleware sends, so this must stay
    byte for byte what it emits.
    """
    return f"A2UI render tool usage guide — how to call {tool_name} with valid arguments."


def _client_tool_names(run_input: Any) -> Set[str]:
    """The names of the tools the client forwarded for this run."""
    names: Set[str] = set()
    for tool in getattr(run_input, "tools", None) or []:
        name = tool.get("name") if isinstance(tool, dict) else getattr(tool, "name", None)
        if isinstance(name, str):
            names.add(name)
    return names


def _client_renders_a2ui(client_tools: Set[str], requested: Union[bool, str]) -> bool:
    """Whether a render tool of the client's own is standing on this run.

    Such a tool draws the surface in the browser, which works only if the
    model read the component list, so on such a run the catalog has to stay in
    the context the model reads. A client that renamed its render tool named
    it in the request.
    """
    wanted = {RENDER_A2UI_TOOL_NAME}
    if isinstance(requested, str):
        wanted.add(requested)
    return bool(wanted & client_tools)


def _without_render_guides(context: List[Any], tool_names: List[str]) -> List[Any]:
    """Drop the usage guides for render tools this run replaces.

    The guide teaches the model to call a tool that is no longer there, so
    leaving it in invites a call to nothing.
    """
    unwanted = {render_guide_description(name) for name in tool_names}
    kept = []
    for entry in context:
        description = entry.get("description") if isinstance(entry, dict) else getattr(entry, "description", None)
        if description not in unwanted:
            kept.append(entry)
    return kept


def prepare_a2ui_run(
    *,
    entity: Any,
    run_input: Any,
    config: Optional[A2UIConfig] = None,
) -> A2UIRunPlan:
    """Work out this request's A2UI arrangements.

    Injection is off unless asked for. The client asks by forwarding
    ``injectA2UITool``; a backend can opt in with ``inject_a2ui_tool`` instead,
    which an explicit ``injectA2UITool: false`` still overrides. A tool the
    developer wired themselves is never injected over, and a tools list the
    agent builds from a callable cannot be read without running it, so such a
    run is declined rather than risking a second tool of the same name.

    The component catalog is taken out of the forwarded context on every run
    whose generation happens here, whether this injected the tool or the
    developer wired it. There it reaches generation through run state instead,
    so a catalog that can run to thousands of tokens is not also pasted into
    every prompt the planner sees. It is left where the client put it on a run
    that carries a render tool of the client's own, which draws in the browser
    and works only if the model read the component list.
    """
    config = validate_a2ui_config(config) or {}

    forwarded_context: List[Any] = list(getattr(run_input, "context", None) or [])
    schema, regular_context = split_a2ui_schema_context(forwarded_context)
    state = build_agui_state(schema, regular_context)
    ag_ui = state["ag-ui"]

    # A remote entity's tools run in the remote deployment, so nothing here can
    # write render progress whatever they are, and listing them would be an
    # HTTP round trip per request.
    remote = is_remote_entity(entity)
    tools = NO_ENTITY_TOOLS if remote else resolve_entity_tools(entity)
    generates = tools.generates_a2ui()
    plan: A2UIRunPlan = {
        "context": forwarded_context,
        "tool": None,
        "drop_tool_names": [],
        "run": A2UIRun(
            # Prepared on a maybe: the channel is a list and an event, unread
            # if nothing ever writes to it, while a run that turns out to
            # generate without one loses progressive painting invisibly.
            render_stream=A2UIRenderStream() if generates is not ToolPresence.ABSENT else None,
            state=state,
            messages=list(getattr(run_input, "messages", None) or []),
        ),
    }

    requested = requested_a2ui_injection(getattr(run_input, "forwarded_props", None), config)
    client_tools = _client_tool_names(run_input)

    def lift_the_catalog_out_of_the_prompt() -> None:
        plan["context"] = regular_context
        # The plan's own entries stay as the router forwarded them; state gets
        # the shape the toolkit can read.
        ag_ui["context"] = _agui_context_entries(regular_context)

    if generates is ToolPresence.PRESENT and not _client_renders_a2ui(client_tools, requested):
        # Generation is wired on the entity itself and reads the catalog from
        # run state, so nothing needs it in the context either.
        lift_the_catalog_out_of_the_prompt()

    if not requested:
        return plan

    if remote:
        # Per-run tools are not forwarded to a remote agent or team at all, so
        # injecting would take the client's render tool away and hand the
        # remote entity nothing in its place, leaving the run with no way to
        # produce a surface. Leave the client's own arrangement standing.
        log_warning(
            "A2UI generation was requested but this run targets a remote agent or team, and per-run tools are "
            "not forwarded to one. Leaving the client's render tool in place; wire get_a2ui_tools() into the "
            "agent in the remote deployment instead."
        )
        return plan

    # Nothing below is injected over what is already there, and each of the
    # three answers is declined differently. Every one leaves the run exactly
    # as the client arranged it, the render tool it injected included.
    tool_name = config.get("tool_name") or GENERATE_A2UI_TOOL_NAME
    carries = tools.carries(tool_name)
    if generates is ToolPresence.PRESENT:
        # The documented way to have generation, so this is the arrangement
        # working rather than a problem to report once per request.
        log_debug(f"A2UI generation is already wired on this agent, so no '{tool_name}' is being added")
        return plan
    if carries is ToolPresence.PRESENT:
        log_warning(
            f"A2UI generation was requested but this agent already has a tool named '{tool_name}', which this "
            "interface knows nothing about. Skipping injection; rename it, or set a2ui={'tool_name': ...} to "
            "inject under another name."
        )
        return plan
    if ToolPresence.UNKNOWN in (generates, carries):
        unreadable = "this entity's own tools are" if not tools.fully_read else "a team member's tools are"
        log_warning(
            f"A2UI generation was requested but {unreadable} a callable resolved when the run starts, so "
            f"whether generation is already wired, or a '{tool_name}' already taken, cannot be known without "
            "running it. Skipping injection, because a second tool of that name would leave the model choosing "
            "between duplicates and take the client's render tool away. Pass the tools as a list, or wire "
            "get_a2ui_tools() into the list the callable returns."
        )
        return plan

    model = getattr(entity, "model", None)
    if model is None:
        log_warning(
            "A2UI generation was requested but this agent has no model to run the render "
            "subagent on. Skipping injection; wire get_a2ui_tools() explicitly instead."
        )
        return plan

    # A truthy string names the render tool the client injected, so a client
    # using a custom name still gets it replaced.
    render_tool_name = requested if isinstance(requested, str) else RENDER_A2UI_TOOL_NAME

    resolved = resolve_a2ui_catalog(state)
    runtime_catalog_id = resolved[1] if resolved else None

    try:
        tool = get_a2ui_tools(
            {
                "model": model,
                "tool_name": tool_name,
                "tool_description": config.get("tool_description"),
                "default_surface_id": config.get("default_surface_id"),
                "default_catalog_id": config.get("default_catalog_id") or runtime_catalog_id,
                "catalog": config.get("catalog"),
                "guidelines": config.get("guidelines"),
                "recovery": config.get("recovery"),
                "on_a2ui_attempt": config.get("on_a2ui_attempt"),
            },
            {
                "tool_choice": config.get("tool_choice", DEFAULT_RENDER_TOOL_CHOICE),
                "subagent_timeout": config.get("subagent_timeout", DEFAULT_RENDER_SUBAGENT_TIMEOUT),
            },
        )
    except Exception as e:
        # Generation was asked for and cannot be given, but the turn itself is
        # still answerable, so run it without A2UI rather than failing outright.
        log_error(f"A2UI generation was requested but the tool could not be built: {e}")
        return plan

    drop_tool_names = [render_tool_name]
    if tool_name != render_tool_name and tool_name in client_tools:
        # Agno keeps the first tool of a name and skips every later one, and a
        # run's client tools are registered ahead of the tool added for it, so
        # left in this one would win and nothing would generate here.
        drop_tool_names.append(tool_name)
        log_warning(
            f"A2UI generation was requested and the client forwarded a tool named '{tool_name}', the name "
            "generation is injected under. Dropping the client's tool for this run, because leaving it in "
            "would disable generation here instead; set a2ui={'tool_name': ...} to inject under another name "
            "and keep it."
        )

    plan["tool"] = tool
    plan["drop_tool_names"] = drop_tool_names
    lift_the_catalog_out_of_the_prompt()
    plan["context"] = _without_render_guides(plan["context"], drop_tool_names)
    plan["run"].render_stream = A2UIRenderStream()
    ag_ui["context"] = _agui_context_entries(plan["context"])
    return plan
