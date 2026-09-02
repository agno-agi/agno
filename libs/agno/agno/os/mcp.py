"""Router for MCP interface providing Model Context Protocol endpoints."""

import functools
import inspect
import logging
import re
from contextlib import contextmanager
from copy import deepcopy
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Iterator,
    List,
    Literal,
    NamedTuple,
    Optional,
    Union,
    get_type_hints,
)
from uuid import uuid4

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.http import (
    StarletteWithLifespan,
)
from fastmcp.tools import ToolResult
from mcp.types import ToolAnnotations

from agno.db.base import SessionType
from agno.os.mcp_results import build_custom_tool_result, build_run_tool_result, trim_session_run
from agno.os.schema import (
    AgentSummaryResponse,
    PaginatedResponse,
    PaginationInfo,
    SessionSchema,
    TeamSummaryResponse,
    WorkflowSummaryResponse,
)
from agno.os.services import runs as run_service
from agno.os.services import sessions as session_service
from agno.os.utils import (
    find_factory_by_id,
    get_db,
    resolve_agent,
    resolve_team,
    resolve_workflow,
    stamped_component_version,
)
from agno.remote.base import BaseRemote, RemoteDb
from agno.run.agent import RunEvent, RunOutput
from agno.run.team import TeamRunEvent, TeamRunOutput
from agno.run.workflow import WorkflowRunEvent, WorkflowRunOutput
from agno.tools.annotations import tool_presentation
from agno.utils.schema import (
    AGNO_INJECTED_PARAMS,
    IDENTITY_INJECTED_PARAMS,
    annotation_binds,
    annotation_reaches,
    identity_injected_types,
    unwrap_annotation,
)
from agno.utils.string import generate_component_id_from_name, generate_id_from_name

if TYPE_CHECKING:
    from agno.os.app import AgentOS
    from agno.os.config import MCPConfig

logger = logging.getLogger(__name__)

# Built-in MCP tools are tagged by domain so they can be scoped as a group. The canonical
# tag set lives in agno/os/config.py next to the MCPConfig fields that consume it --
# single source of truth so adding a new tag is a one-place change.
from agno.os.config import MCP_BUILTIN_TAGS as _BUILTIN_TOOL_TAGS  # noqa: E402

# Names of the default (built-in) tools by tag set, used to detect name collisions with
# exposed components before registration. Keep in sync with the ``name=`` / ``tags=``
# arguments on each ``@register_builtin_tool(...)`` below; a unit test asserts this map
# matches the tools a default server actually registers. continue_run/cancel_run carry
# ``lifecycle`` alongside ``core`` so they can ride along with exposed components even
# when the rest of the default surface is off.
_BUILTIN_TOOL_NAMES: Dict[str, frozenset] = {
    "get_agentos_config": frozenset({"core"}),
    "run_agent": frozenset({"core"}),
    "run_team": frozenset({"core"}),
    "run_workflow": frozenset({"core"}),
    "continue_run": frozenset({"core", "lifecycle"}),
    "cancel_run": frozenset({"core", "lifecycle"}),
    "get_sessions": frozenset({"session"}),
    "get_session_runs": frozenset({"session"}),
}

# What a published component's run tool asserts about itself, before the deployer's own
# ``as_tool(annotations=...)``. A run is not read-only (it persists a session and may
# call side-effectful tools) and reaches beyond this server.
#
# All three of readOnlyHint/destructiveHint/openWorldHint are stated rather than left
# implicit, here and on every built-in tool. An omitted hint is not "unknown" to a
# client -- it falls back to a protocol default -- and a directory submission scan
# rejects a tool that leaves any of the three unset, so a hint the server declines to
# state is a hint someone else answers on its behalf.
#
# openWorldHint asks whether a tool can reach a system this deployment does not own.
# The run tools can, because the component they run may call anything, and so can
# cancel_run: cancelling a Remote* component's run is an outbound HTTP call to that
# deployment. The config and session tools only read storage this deployment owns.
_EXPOSED_COMPONENT_ANNOTATIONS: Dict[str, Any] = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "openWorldHint": True,
}


def _enabled_builtin_tags(config: "Optional[MCPConfig]", has_exposures: bool = False) -> set:
    """Resolve which built-in tool tags should be registered, given the MCP config.

    ``lifecycle`` never enters the set implicitly: with the default surface on,
    continue_run/cancel_run are ordinary core tools (``exclude_tags={"core"}`` removes
    them, exactly as it did before the tag existed -- tools register on tag
    INTERSECTION, so an implicitly enabled ``lifecycle`` would resurrect the dual-tagged
    pair on a surface that excluded ``core``). The tag is added only when named
    explicitly in ``include_tags``, or by the exposure ride-along below: an exposed
    component can pause on a HITL tool, and without continue_run the pause would be a
    dead end over MCP. Both ride-along off-switches are honoured --
    ``lifecycle_tools=False`` and an explicit ``exclude_tags={"lifecycle"}`` -- and
    both gate ONLY the ride-along; neither strips the pair from an enabled ``core``
    surface.
    """
    if config is None:
        return set(_BUILTIN_TOOL_TAGS) - {"lifecycle"}
    if not config.default_tools:
        enabled: set = set()
    else:
        # An explicitly empty include_tags set means "no built-in tools", so test
        # against None rather than truthiness.
        enabled = (
            set(config.include_tags) if config.include_tags is not None else set(_BUILTIN_TOOL_TAGS) - {"lifecycle"}
        )
        if config.exclude_tags:
            enabled -= set(config.exclude_tags)
    if has_exposures and config.lifecycle_tools and "lifecycle" not in (config.exclude_tags or set()):
        enabled.add("lifecycle")
    return enabled


def _builtin_tool_registrar(mcp: FastMCP, enabled_tags: set):
    """Return a drop-in replacement for ``mcp.tool`` that scopes the built-in tools.

    When a tool's tags intersect the enabled set, the tool is registered as usual.
    Otherwise the decorator is a no-op (the function is returned unregistered), so
    scoping happens at registration time without depending on FastMCP tool-removal APIs.
    """

    def register(*args: Any, **kwargs: Any):
        tags = kwargs.get("tags") or set()
        if tags & enabled_tags:
            title, annotations = tool_presentation(
                kwargs.get("title"), kwargs.get("annotations"), source=f"built-in tool {kwargs.get('name')!r}"
            )
            if annotations is not None:
                kwargs["annotations"] = annotations
            return mcp.tool(*args, **kwargs)

        def _skip(fn: Any) -> Any:
            return fn

        return _skip

    return register


def _register_custom_tools(mcp: FastMCP, entries: List[Any], enabled_tags: "Optional[set]" = None) -> Dict[str, str]:
    """Register the custom-tool entries (callables and Agno tools) on the MCP server.

    Entries are pre-classified by ``_split_tool_entries`` -- components and
    ``ComponentTool`` markers never reach here. Returns the names the tools actually
    registered under (FastMCP's own naming, e.g. ``functools.partial`` objects register
    as "partial"), so the exposure collision check downstream sees the real registry
    rather than a re-derivation.

    A ``Toolkit`` is flattened into one MCP tool per method, the way an agent takes it
    apart. Each flattened name goes through the same collision check as a hand-written
    custom tool, so a toolkit method named like a default tool (``WorkflowTools`` really
    does register ``run_workflow``) is a startup error rather than a silent replacement.

    A custom tool named like a default tool that will register (its tags intersect
    ``enabled_tags``), or like an earlier custom tool, is a hard error, matching the
    exposure path: FastMCP would otherwise warn-and-REPLACE, so a custom
    ``continue_run`` would silently shadow the riding builtin (while paused results
    keep steering callers to the builtin's schema), and a duplicate custom name would
    silently swallow the first tool.
    """
    from agno.tools.toolkit import Toolkit

    taken = {
        builtin: f'the default tool "{builtin}"'
        for builtin, tags in _BUILTIN_TOOL_NAMES.items()
        if tags & (enabled_tags or set())
    }
    names: Dict[str, str] = {}
    for tool in entries:
        if isinstance(tool, Toolkit):
            # ``get_async_functions()`` is the merged surface with async variants
            # preferred -- the same set an agent running in async mode would get --
            # already filtered by the toolkit's include_tools/exclude_tools.
            members = list(tool.get_async_functions().values())
            if not members:
                raise ValueError(
                    f'MCPConfig.tools got toolkit "{tool.name}", which registers no functions, so it would '
                    "publish nothing. A toolkit that discovers its tools while connecting (MCPTools) has to "
                    "be connected before the server is built; otherwise widen its include_tools/exclude_tools, "
                    "or drop it."
                )
            for member in members:
                name = _register_custom_tool(mcp, member, taken=taken, enabled_tags=enabled_tags, toolkit=tool)
                # The label names the toolkit, because a collision on a flattened method
                # is not fixed by renaming a "custom tool" the deployer never wrote.
                label = f'toolkit "{tool.name}" tool "{name}"'
                names[name] = label
                taken[name] = label
            continue
        name = _register_custom_tool(mcp, tool, taken=taken, enabled_tags=enabled_tags)
        label = f'custom tool "{name}"'
        names[name] = label
        taken[name] = label
    return names


def _collision_free_advice(colliding_name: str, enabled_tags: "Optional[set]") -> str:
    """The action clause of a name-collision error: how to free ``colliding_name``.

    The run-lifecycle pair (continue_run/cancel_run) is tagged BOTH "core" and
    "lifecycle", and rides along with any exposure. So "is this a lifecycle tool" is
    always true for it and cannot decide the advice -- what matters is HOW the name got
    onto the server. When it was claimed solely via the ride-along ("core" not enabled),
    only the lifecycle switches free it; when "core" is enabled the pair registers as a
    core default and the lifecycle switches do nothing (core keeps re-adding it), so the
    caller must drop core too.
    """
    tags = _BUILTIN_TOOL_NAMES.get(colliding_name) or frozenset()
    if "lifecycle" in tags and "core" not in (enabled_tags or set()):
        return 'or drop the run-lifecycle pair via lifecycle_tools=False or exclude_tags={"lifecycle"} '
    return "or scope the default tool out via default_tools/include_tags/exclude_tags "


def _custom_tool_presentation(tool: Any) -> "tuple[Optional[str], Optional[ToolAnnotations]]":
    """The ``title`` / ``annotations`` an Agno ``Function`` publishes, if it is one.

    ``Tool.from_function`` takes a ``ToolAnnotations`` model rather than a dict (the
    ``mcp.tool`` decorator accepts either), so the Function's dict is converted here.
    """
    from agno.tools.function import Function

    if not isinstance(tool, Function):
        return None, None
    title, annotations = tool_presentation(
        tool.title, tool.annotations, source=f"@tool(annotations=...) on {tool.name!r}"
    )
    return title, (ToolAnnotations(**annotations) if annotations else None)


class _Hidden(NamedTuple):
    """One parameter kept out of an MCP tool's schema, and what the server puts in it.

    ``bind`` is None when the server has nothing to put there: the parameter is still
    hidden (pydantic could not describe it) but its own default stands. ``always``
    writes the bound value even over a non-empty default, which is what the reserved
    names get -- an authenticated caller's identity is never the tool author's to
    default away.
    """

    bind: Optional[Callable[[], Any]]
    always: bool


# A hidden parameter has to be passed by keyword at call time. The other kinds cannot
# be, so a framework-typed one among them is refused by name rather than left in the
# schema for pydantic to fail on.
_MCP_INJECTABLE_KINDS = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)

# Approval gates that live in ``FunctionCall.execute``. An MCP call runs the entrypoint
# directly, so a tool carrying one of these would run its body with the gate skipped.
_MCP_UNSUPPORTED_GATES = ("requires_confirmation", "requires_user_input", "external_execution", "approval_type")


def _new_mcp_run_context() -> Any:
    """A RunContext for one MCP tool call, carrying the authenticated caller.

    There is no run and no session behind an MCP tool call, so both ids are fresh per
    call: what a tool writes into ``session_state`` here is not read back by the next
    call. ``user_id`` is the part that carries real information -- the JWT subject, the
    same value ``user_id`` injection resolves.
    """
    from agno.run.base import RunContext

    return RunContext(run_id=str(uuid4()), session_id=str(uuid4()), user_id=_resolve_user_id(None))


def _identity_binder(hint: Any) -> "Optional[Callable[[], Any]]":
    """What the server can put INTO a parameter of this type, or None for nothing.

    Deliberately narrower than the rule that decides what to HIDE, and mirroring
    ``FunctionCall._build_entrypoint_args``: a ``List[RunContext]`` names an identity
    type, so it cannot stay in the schema, but it holds run contexts rather than being
    one and nothing can be bound into it. Agent and Team bind None because an MCP tool
    call runs outside any component.
    """
    from agno.agent.agent import Agent
    from agno.run.base import RunContext
    from agno.team.team import Team

    hint = unwrap_annotation(hint)
    if annotation_binds(hint, (RunContext,)):
        return _new_mcp_run_context
    if annotation_binds(hint, (Agent, Team)):
        return lambda: None
    return None


def _toolkit_clause(toolkit: Any, method: "Optional[str]") -> str:
    """The 'or drop it from the toolkit' half of a refusal, when one applies."""
    if toolkit is None:
        return ""
    return f' (or drop it from toolkit "{toolkit.name}" with exclude_tools=["{method}"])'


def _mcp_hidden_params(
    fn: Callable,
    owner: "Optional[str]",
    reserved_names: bool = False,
    toolkit: Any = None,
    drop_var_keyword: bool = False,
) -> "Dict[str, _Hidden]":
    """The parameters kept out of an MCP tool's schema, and how each one is filled.

    Two rules, each mirroring one the agent-facing path already uses:

      * By NAME -- ``user_id`` always, because the JWT subject is the server's to
        resolve and never the caller's to supply. For an Agno ``Function`` the identity
        names the framework fills itself (``agent``/``team``/``run_context`` and the
        ``_agno_`` channels) are hidden too: that object is the same one an agent would
        run, and it must not have two contracts. A bare callable handed to
        ``MCPConfig.tools`` was written for this surface, so its own ``agent: str``
        stays its own. Media names are hidden on NEITHER path -- nothing here has run
        media to inject, so hiding one would leave it fillable by nobody.
      * By TYPE -- any annotation that can REACH an identity type. This is broader than
        the model-facing ``is_framework_typed`` on purpose. That rule keeps
        ``owner: Union[str, Agent]`` fillable because a model can only ever send the
        string half; here pydantic builds the schema from the real signature and fails
        on ``BaseDb`` regardless of what the caller would have sent.

    A parameter the server must fill but cannot pass by keyword, and a required one
    nothing can be bound into, are refused by name -- otherwise they surface at startup
    as a pydantic error naming a type the tool author never wrote.
    """
    try:
        sig = inspect.signature(fn)
    except (ValueError, TypeError):
        return {}

    hidden: Dict[str, _Hidden] = {}

    def claim(param_name: str, entry: _Hidden) -> None:
        param = sig.parameters[param_name]
        if param.kind not in _MCP_INJECTABLE_KINDS:
            raise ValueError(
                f'MCP custom tool "{owner}" declares "{param_name}" as a {param.kind.description} parameter. '
                "The server has to fill it -- pydantic cannot build a tool schema for it -- and cannot pass "
                f"it by keyword. Make it a normal or keyword-only parameter{_toolkit_clause(toolkit, owner)}."
            )
        hidden[param_name] = entry

    # ``user_id`` is hidden on the hand-written path only. That contract was written for
    # a tool authored FOR this surface, where the name means "who is calling". A toolkit
    # method takes its identity from the RunContext instead -- agno never injects
    # ``user_id`` by name -- so a ``user_id`` argument there is a domain value
    # (``ZoomTools.get_upcoming_meetings(user_id="me")`` asks which Zoom account to read),
    # and overwriting it with the JWT subject would break the call rather than secure it.
    if drop_var_keyword:
        # ``**kwargs`` has no MCP schema -- FastMCP refuses the tool outright rather than
        # publishing one -- so a catch-all that the Function does not describe separately
        # is dropped from what clients see. The named parameters beside it still describe
        # the tool (EmailTools.email_user(subject, body, **kwargs)), and nothing fills it:
        # an MCP caller sends a JSON object, which binds to the named parameters anyway.
        for param_name, param in sig.parameters.items():
            if param.kind is inspect.Parameter.VAR_KEYWORD:
                hidden[param_name] = _Hidden(bind=None, always=False)

    by_name = (() if toolkit is not None else ("user_id",)) + (IDENTITY_INJECTED_PARAMS if reserved_names else ())
    for param_name in by_name:
        if param_name not in sig.parameters:
            continue
        if param_name == "user_id":
            claim(param_name, _Hidden(bind=lambda: _resolve_user_id(None), always=True))
        elif param_name in ("run_context", "_agno_run_context"):
            claim(param_name, _Hidden(bind=_new_mcp_run_context, always=True))
        else:
            claim(param_name, _Hidden(bind=lambda: None, always=True))

    try:
        hints = get_type_hints(fn)
    except Exception:
        # One unreadable annotation fails the whole walk. The reserved names above still
        # stand; the typed rule is skipped rather than guessed at by evaluating
        # annotation text, which would run the tool author's strings at startup.
        hints = {}

    for param_name, hint in hints.items():
        # get_type_hints includes "return", which is not a parameter.
        if param_name == "return" or param_name not in sig.parameters or param_name in hidden:
            continue
        # Per parameter, not per signature: one annotation this walk cannot read must not
        # leave a neighbouring identity parameter unclassified and caller-facing.
        try:
            owned = annotation_reaches(hint, identity_injected_types())
        except Exception:
            owned = True  # Cannot classify it, so do not put it in the schema.
        if not owned:
            continue
        binder = _identity_binder(hint)
        if binder is None and sig.parameters[param_name].default is inspect.Parameter.empty:
            raise ValueError(
                f'MCP custom tool "{owner}" declares required parameter "{param_name}" as {hint!r}, which the '
                "server must keep out of the tool schema but has nothing to fill it with. Drop it from the "
                "signature, or give it a default and expect that default on every call"
                f"{_toolkit_clause(toolkit, owner)}."
            )
        claim(param_name, _Hidden(bind=binder, always=False))

    return hidden


def _reject_gated_function(tool: Any, name: "Optional[str]", toolkit: Any) -> None:
    """Refuse a tool whose approval gate this surface cannot honour.

    Confirmation, user input and external execution all live in ``FunctionCall.execute``.
    An MCP call reaches the entrypoint directly, so publishing such a tool would run the
    gated body with no gate -- ``Workspace`` alone would put ``delete_file`` and
    ``run_command`` on the wire ungated. Refused at startup rather than downgraded.
    """
    gates = [gate for gate in _MCP_UNSUPPORTED_GATES if getattr(tool, gate, None)]
    if not gates:
        return
    raise ValueError(
        f'MCP custom tool "{name}" sets {", ".join(gates)}, which the MCP server cannot honour: an MCP call '
        "runs the tool directly, so the approval step would be skipped. Drop the gate for this surface"
        f"{_toolkit_clause(toolkit, name)}."
    )


def _takes_var_keyword(fn: Callable) -> bool:
    """Whether the callable ends in ``**kwargs``, which FastMCP refuses to publish."""
    try:
        return any(param.kind is inspect.Parameter.VAR_KEYWORD for param in inspect.signature(fn).parameters.values())
    except (ValueError, TypeError):
        return False


def _declares_own_schema(tool: Any, entrypoint: Callable) -> bool:
    """Whether this Function carries the schema its signature cannot express.

    A dynamic toolkit builds its tools at runtime and puts the schema on the Function
    rather than in the signature: ``MCPTools`` copies each remote tool's ``inputSchema``,
    ``ApifyTools`` takes ``**kwargs`` and describes the actor's inputs separately. FastMCP
    derives its schema by introspecting the callable, which for those refuses outright --
    "Functions with **kwargs are not supported as tools" -- and takes the whole server
    down with it.

    True only when the entrypoint genuinely cannot describe itself AND the Function does.
    Everywhere else the signature stays the source of truth, so an ordinary tool is
    unaffected.
    """
    from agno.tools.function import Function

    if not isinstance(tool, Function) or not _takes_var_keyword(entrypoint):
        return False
    parameters = tool.parameters
    return isinstance(parameters, dict) and bool(parameters.get("properties"))


def _declared_parameters(tool: Any, entrypoint: Callable, hidden: "Dict[str, _Hidden]") -> "Dict[str, Any]":
    """The Function's declared schema, minus the names the server fills itself.

    Only two things are removed, and both are ones the caller could not have meant.
    Whatever the signature hid is dropped because the wrapper injects it, and the
    ``_agno_``-prefixed channels are dropped because they are agno's own wire names.

    The bare identity names are deliberately NOT dropped. A declared schema reaches this
    point because the signature could not describe the tool -- typically a remote tool's
    own ``inputSchema``, proxied through ``MCPTools`` -- and ``agent`` or ``team`` there
    belongs to the far side. Removing them hid a legitimate argument from the model while
    a client could still send it: FastMCP validates against the declared schema (see
    ``_schema_validator``) but the name never reached anything of agno's either way.

    The catch-all's own name goes too. agno derives a property literally named after it
    from a Google-style ``Args:`` docstring, and publishing a required ``kwargs`` of
    unspecified type describes nothing a caller can fill.
    """
    owned = set(hidden) | set(AGNO_INJECTED_PARAMS)
    try:
        owned.update(
            name
            for name, param in inspect.signature(entrypoint).parameters.items()
            if param.kind is inspect.Parameter.VAR_KEYWORD
        )
    except (ValueError, TypeError):
        pass

    declared = deepcopy(tool.parameters)
    properties = {name: schema for name, schema in declared.get("properties", {}).items() if name not in owned}
    declared["properties"] = properties
    required = [name for name in declared.get("required", []) or [] if name in properties]
    if required:
        declared["required"] = required
    else:
        declared.pop("required", None)
    return declared


def _schema_validator(schema: "Dict[str, Any]") -> "Optional[Callable[[Dict[str, Any]], None]]":
    """A checker for arguments against a declared schema, or None if it cannot be built.

    An ordinary tool gets this for free: FastMCP builds a pydantic model from the
    signature, so a missing argument or a wrong type is rejected before the body runs. A
    declared schema skips that machinery entirely, which left two tools on the same
    server disagreeing about whether a malformed call is an error -- and a malformed call
    from a model is ordinary traffic, not an attack.

    ``jsonschema`` ships with the MCP stack itself, so this costs no new dependency; if it
    is somehow absent the tool keeps working exactly as it did, unvalidated.
    """
    try:
        from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
    except Exception:
        return None
    try:
        validator = Draft202012Validator(schema)
    except Exception:
        # A schema this validator cannot compile is the remote's to fix, not a reason to
        # refuse the tool: it was serving unvalidated a moment ago.
        return None

    def validate(arguments: "Dict[str, Any]") -> None:
        errors = sorted(validator.iter_errors(arguments), key=lambda error: list(error.path))
        if not errors:
            return
        detail = "; ".join(
            f"{'.'.join(str(part) for part in error.path) or '<root>'}: {error.message}" for error in errors[:5]
        )
        raise ToolError(f"Invalid arguments: {detail}")

    return validate


def _register_custom_tool(
    mcp: FastMCP,
    tool: Any,
    taken: "Optional[Dict[str, str]]" = None,
    enabled_tags: "Optional[set]" = None,
    toolkit: Any = None,
) -> str:
    """Register a single custom tool, supporting plain callables and Agno tools/Functions.

    Returns the name the tool registered under. ``taken`` holds names already claimed
    on this server (checked before registration -- FastMCP replaces on duplicates
    rather than raising). ``enabled_tags`` steers the collision advice toward the knob
    that actually frees the name. ``toolkit`` is the toolkit this tool was flattened
    out of, used only to point a refusal at the knob that frees it.
    """
    from fastmcp.tools import FunctionTool, Tool

    # Agno tool / Function: a callable ``entrypoint`` plus name/description metadata.
    entrypoint = getattr(tool, "entrypoint", None)
    if callable(entrypoint):
        name = getattr(tool, "name", None) or getattr(entrypoint, "__name__", None)
        description = getattr(tool, "description", None)
        _reject_gated_function(tool, name, toolkit)
        uses_declared_schema = _declares_own_schema(tool, entrypoint)
        hidden = _mcp_hidden_params(
            entrypoint,
            owner=name,
            reserved_names=True,
            toolkit=toolkit,
            # A declared schema is published verbatim, so the catch-all it is declared
            # THROUGH has to stay in the wrapper's signature to receive the arguments.
            drop_var_keyword=not uses_declared_schema,
        )
        # Presentation metadata is read only from an Agno Function, never duck-typed off
        # an arbitrary object: a stray ``.annotations`` attribute on some other tool-ish
        # object means something else entirely. Marketplace scans reject tools that carry
        # no annotations, so a custom tool that wants a listing sets them on its Function.
        title, annotations = _custom_tool_presentation(tool)
        returns_tool_result = _returns_tool_result(entrypoint)
        wrapped = _build_mcp_wrapper(entrypoint, hidden, convert_result=returns_tool_result)
        if uses_declared_schema:
            declared = _declared_parameters(tool, entrypoint, hidden)
            # Built directly rather than through ``Tool.from_function``, which would
            # re-derive the schema from a signature that cannot express one.
            tool_obj = FunctionTool(
                fn=_build_mcp_wrapper(
                    entrypoint, hidden, convert_result=returns_tool_result, validate=_schema_validator(declared)
                ),
                name=name,
                title=title,
                description=description,
                annotations=annotations,
                parameters=declared,
            )
        else:
            tool_obj = Tool.from_function(
                wrapped,
                name=name,
                title=title,
                description=description,
                annotations=annotations,
                # A ``ToolResult`` return is converted into content blocks on the way
                # out, so the schema FastMCP would derive from that model describes
                # something the tool never sends.
                **({"output_schema": None} if returns_tool_result else {}),
            )
    elif callable(tool):
        # Plain callable: name/description inferred from ``__name__``/docstring.
        hidden = _mcp_hidden_params(tool, owner=getattr(tool, "__name__", "custom tool"), drop_var_keyword=True)
        returns_tool_result = _returns_tool_result(tool)
        tool_obj = Tool.from_function(
            _build_mcp_wrapper(tool, hidden, convert_result=returns_tool_result),
            **({"output_schema": None} if returns_tool_result else {}),
        )
    else:
        raise TypeError(
            f"Cannot register MCP tool of type {type(tool).__name__!r}; expected a callable or an Agno tool/Function."
        )

    if taken and tool_obj.name in taken:
        claimant = taken[tool_obj.name]
        # A flattened toolkit method is not the deployer's to rename -- the name comes
        # from someone else's class -- so its advice names the knob that frees it.
        free_it = (
            f'Drop it from toolkit "{toolkit.name}" with exclude_tools=["{tool_obj.name}"]'
            if toolkit is not None
            else "Rename the custom tool"
        )
        if claimant.startswith("the default tool"):
            advice = f"{free_it}, {_collision_free_advice(tool_obj.name, enabled_tags)}so each tool name is unique."
        elif toolkit is not None:
            advice = f"{free_it} so each tool name is unique."
        else:
            advice = "Rename one of them so each tool name is unique."
        raise ValueError(f'MCP custom tool name "{tool_obj.name}" collides with {claimant}. {advice}')
    mcp.add_tool(tool_obj)
    return tool_obj.name


def _returns_tool_result(fn: Callable) -> bool:
    """Whether the callable declares an Agno ``ToolResult`` return.

    Read from the annotation rather than discovered at call time, because the same
    answer settles two things at once: the result needs converting, and FastMCP must be
    told NOT to derive an output schema from the ``ToolResult`` model -- otherwise
    ``tools/list`` advertises a ToolResult-shaped ``outputSchema`` describing something
    the tool never sends.
    """
    from agno.tools.function import ToolResult

    try:
        hint = get_type_hints(fn).get("return")
    except Exception:
        hint = getattr(fn, "__annotations__", {}).get("return")
    return isinstance(hint, type) and issubclass(hint, ToolResult)


def _converted_result(value: Any) -> Any:
    """An Agno ``ToolResult`` rendered as MCP content; anything else untouched."""
    from agno.tools.function import ToolResult

    if isinstance(value, ToolResult):
        return build_custom_tool_result(value)
    return value


def _build_mcp_wrapper(
    fn: Callable,
    hidden: "Dict[str, _Hidden]",
    convert_result: bool = False,
    validate: "Optional[Callable[[Dict[str, Any]], None]]" = None,
) -> Callable:
    """Give FastMCP a signature without the framework's parameters, and fill them in.

    On the agent-facing path FunctionCall assembles the arguments after the schema is
    settled, so hiding and filling are separate steps. Here FastMCP reads this signature
    to BUILD the schema, so a RunContext left in it is not merely exposed: pydantic
    cannot describe one, and the server fails to start. The wrapper therefore drops the
    hidden parameters from its own signature and puts the values back on the way through.

    ``convert_result`` additionally renders an Agno ``ToolResult`` as MCP content blocks
    on the way out, instead of letting it reach FastMCP's generic JSON serializer.

    Tools with nothing to hide and nothing to convert are returned unchanged, so they
    register exactly as they did before this wrapper existed.
    """
    if not hidden and not convert_result and validate is None:
        return fn

    sig = inspect.signature(fn)
    visible = [param for name, param in sig.parameters.items() if name not in hidden]
    new_sig = sig.replace(parameters=visible)
    # Positional arguments can only be re-bound by name when every visible parameter can
    # take a keyword. Without that step a hidden parameter sitting BEFORE a visible one
    # -- the shape of every RunContext-taking toolkit method -- would collide with its
    # own injected value on a positional call.
    positional_names = (
        [param.name for param in visible] if all(p.kind in _MCP_INJECTABLE_KINDS for p in visible) else []
    )

    def visible_annotations() -> Dict[str, Any]:
        """The annotations of the parameters that survived, plus the return type.

        ``functools.wraps`` copies the wrapped function's ``__annotations__`` wholesale,
        hidden parameters included -- and it copies the same dict object, so this builds
        a new one rather than deleting from the original's. FastMCP reads annotations as
        well as the signature, so a hidden parameter's annotation left behind is not
        cosmetic: one that cannot be resolved at all (a framework type imported only
        under ``if TYPE_CHECKING``) fails FastMCP's type adapter and the server never
        starts, even though the parameter was correctly hidden.
        """
        annotations = {
            param.name: param.annotation for param in visible if param.annotation is not inspect.Parameter.empty
        }
        if new_sig.return_annotation is not inspect.Signature.empty:
            annotations["return"] = new_sig.return_annotation
        return annotations

    def prepare(args: tuple, kwargs: Dict[str, Any]) -> tuple:
        if validate is not None and not args:
            # Before injection, so the schema is checked against what the caller sent
            # rather than against the framework values it never sees.
            validate(kwargs)
        if args and positional_names and len(args) <= len(positional_names):
            names = positional_names[: len(args)]
            if not any(name in kwargs for name in names):
                kwargs.update(zip(names, args))
                args = ()
        for param_name, entry in hidden.items():
            if entry.bind is None:
                continue  # Hidden but unfillable: the parameter's own default stands.
            value = entry.bind()
            if entry.always or value is not None or sig.parameters[param_name].default is inspect.Parameter.empty:
                kwargs[param_name] = value
        return args

    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            result = await fn(*prepare(args, kwargs), **kwargs)
            return _converted_result(result) if convert_result else result

        async_wrapper.__signature__ = new_sig  # type: ignore[attr-defined]
        async_wrapper.__annotations__ = visible_annotations()
        return async_wrapper

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        result = fn(*prepare(args, kwargs), **kwargs)
        return _converted_result(result) if convert_result else result

    wrapper.__signature__ = new_sig  # type: ignore[attr-defined]
    wrapper.__annotations__ = visible_annotations()
    return wrapper


def _resolve_user_id(caller_user_id: Optional[str]) -> Optional[str]:
    """Bind user_id to the JWT subject when an authenticated request is in flight."""
    from fastmcp.server.dependencies import get_http_request

    try:
        request = get_http_request()
    except RuntimeError:
        return caller_user_id

    state_user_id = getattr(getattr(request, "state", None), "user_id", None)
    if state_user_id is not None:
        return state_user_id
    return caller_user_id


def _forwarded_auth_token() -> Optional[str]:
    """The caller's inbound bearer token, for forwarding to Remote* components.

    Remote run/continue/cancel take an ``auth_token`` and build their own Authorization
    header from it (the REST routers forward the same token on every remote call), so a
    JWT/PAT-protected downstream AgentOS accepts the proxied request instead of 401ing.
    """
    from fastmcp.server.dependencies import get_http_request

    from agno.os.auth import get_auth_token_from_request

    try:
        request = get_http_request()
    except RuntimeError:
        return None
    return get_auth_token_from_request(request)


def _forwarded_auth_headers() -> Optional[Dict[str, str]]:
    """The caller's bearer token as an Authorization header for downstream RemoteDb calls.

    Mirrors the REST routers, which forward the inbound token on every RemoteDb call so
    a JWT/PAT-protected downstream AgentOS accepts the request.
    """
    token = _forwarded_auth_token()
    return {"Authorization": f"Bearer {token}"} if token else None


def _scoped_caller_user_id() -> Optional[str]:
    """The caller's user_id when they are a non-admin, isolation-scoped principal, else None.

    Reuses the REST scoping rule (:func:`get_scoped_user_id`): admins and
    non-isolated deployments return None (no per-run ownership gate), while a
    scoped user returns their id so run-lifecycle tools can enforce ownership.
    """
    from fastmcp.server.dependencies import get_http_request

    from agno.os.middleware.user_scope import get_scoped_user_id

    try:
        request = get_http_request()
    except RuntimeError:
        return None
    return get_scoped_user_id(request)


def _scoped_read_user_id(caller_user_id: Optional[str]) -> Optional[str]:
    """The user_id a session-read tool should filter by.

    Mirrors the REST session routes (``resolve_db_and_scope(fallback_user_id=user_id)``): a
    scoped, non-admin caller under user isolation is pinned to their own id, while admins and
    non-isolation deployments honour the client-supplied ``user_id``. This differs from
    :func:`_resolve_user_id` (used by the run tools for attribution), which always forces the
    authenticated id -- so an admin can still read another user's sessions over MCP, as on REST.
    """
    scoped = _scoped_caller_user_id()
    return scoped if scoped is not None else caller_user_id


@functools.lru_cache(maxsize=1)
def _tool_scope_mappings() -> Dict[str, List[str]]:
    """The default route→scope mappings, built once (they are static data)."""
    from agno.os.scopes import get_default_scope_mappings

    return get_default_scope_mappings()


def _mcp_auth_enabled(request: Any) -> bool:
    """Whether this request is served by an ``mcp_auth``-protected MCP app.

    ``get_mcp_server`` stamps the flag on the sub-app's state; the mounted app is the
    innermost Starlette app, so ``request.app`` resolves to it inside the tools.
    """
    app = getattr(request, "app", None)
    return bool(getattr(getattr(app, "state", None), "agno_mcp_auth_enabled", False))


_MISSING_BRIDGE_DETAIL = (
    "Authorization context missing: the request was authenticated by the mcp_auth provider "
    "but the identity bridge did not populate request.state. Denying rather than skipping "
    "enforcement."
)


def _require_tool_scopes(method: str, path: str) -> None:
    """Enforce the caller's scopes against the REST route this tool call is equivalent to.

    The MCP tools are an alternate transport for the REST surface, so authorization
    reuses the REST mechanism verbatim: map the tool call onto its REST route and run
    ``check_route_scopes`` with the same mappings (per-resource scopes and the admin
    bypass behave identically). Service-account scopes are ACL data enforced in every
    deployment mode, mirroring ``agno.os.auth._authenticate_service_account``; JWT
    scopes are enforced when authorization is enabled. Anonymous callers (open or
    security-key deployments) carry no scopes and pass.

    Custom ``scope_mappings`` passed to a manually-installed JWTMiddleware apply to the
    literal request path (``/mcp``), not to these synthetic routes -- the tool gate
    always enforces the default mappings.
    """
    from fastmcp.server.dependencies import get_http_request

    from agno.os.auth import build_insufficient_permissions_detail
    from agno.os.scopes import check_route_scopes

    try:
        request = get_http_request()
    except RuntimeError:
        return

    state = request.state
    is_service_account = getattr(state, "service_account_name", None) is not None
    if not is_service_account and not getattr(state, "authorization_enabled", False):
        # Under mcp_auth, a verified request whose identity bridge did NOT run (an
        # ordering regression) has no ``authenticated`` marker -- fail closed rather than
        # silently disabling enforcement. But a request the bridge DID authenticate whose
        # token simply carries no RBAC (an RBAC-off agno JWT, or an external Tier-2 token
        # whose AS is the authority) is a legitimate unenforced caller and skips agno
        # scope enforcement, exactly as on a non-mcp_auth deployment. Without mcp_auth the
        # skip is the intended open/security-key behavior.
        if _mcp_auth_enabled(request) and not getattr(state, "authenticated", False):
            raise Exception(_MISSING_BRIDGE_DETAIL)
        return

    admin_scope_raw = getattr(state, "admin_scope", None)
    admin_scope = admin_scope_raw if isinstance(admin_scope_raw, str) else None
    scope_check = check_route_scopes(
        list(getattr(state, "scopes", None) or []),
        _tool_scope_mappings(),
        method,
        path,
        admin_scope=admin_scope,
    )
    if not scope_check.allowed:
        # Under mcp_auth, a scope denial is most often an external-AS misconfiguration
        # (the token carries non-agno scopes), which the client-facing 403 can't point at.
        # Log the presented-vs-required scopes and the AS-config hint so the deployer can
        # trace it to their authorization server. Behavior (the raised 403) is unchanged.
        if _mcp_auth_enabled(request):
            from agno.utils.log import log_warning

            log_warning(
                f"MCP tool scope check failed for {method} {path}: caller presented "
                f"{list(getattr(state, 'scopes', None) or [])}, required {scope_check.required_scopes}. "
                "If this is a Tier-2 (external authorization server) deployment, configure your AS to emit "
                "agno-format scopes in the token 'scope' claim."
            )
        raise Exception(build_insufficient_permissions_detail(scope_check.required_scopes))


async def _enforce_run_continuation_allowed(db: Any, run_id: str) -> None:
    """Block continuing a run that is awaiting admin approval.

    The REST ``/continue`` routes gate this with ``require_approval_resolved``; the MCP
    ``continue_run`` tool must apply the same gate or a run's initiator could self-approve
    an admin-required pause by continuing over MCP instead of REST. Both share
    ``run_continuation_blocked_reason`` so the policy cannot drift.
    """
    from fastmcp.server.dependencies import get_http_request

    from agno.os.auth import run_continuation_blocked_reason

    try:
        request = get_http_request()
    except RuntimeError:
        # No HTTP request in scope (e.g. stdio transport): request.state auth context is
        # unavailable, so there is nothing to enforce here.
        return

    state = request.state
    if (
        _mcp_auth_enabled(request)
        and not getattr(state, "authenticated", False)
        and getattr(state, "service_account_name", None) is None
        and not getattr(state, "authorization_enabled", False)
    ):
        # Same fail-closed rule as _require_tool_scopes: a provider-verified request whose
        # identity bridge did not run (no ``authenticated`` marker) must not bypass the
        # approval gate. A bridged RBAC-off caller is legitimate and proceeds.
        raise Exception(_MISSING_BRIDGE_DETAIL)
    reason = await run_continuation_blocked_reason(
        db,
        run_id,
        authorization_enabled=bool(getattr(state, "authorization_enabled", False)),
        user_scopes=list(getattr(state, "scopes", None) or []),
    )
    if reason:
        raise Exception(reason)


# Events forwarded to the client as progress notifications during agent/team runs.
# Content deltas are deliberately excluded: MCP progress is a status channel, and
# per-token notifications would flood clients that request a progress token.
_TOOL_CALL_PROGRESS_EVENTS = frozenset(
    {
        RunEvent.tool_call_started.value,
        RunEvent.tool_call_completed.value,
        TeamRunEvent.tool_call_started.value,
        TeamRunEvent.tool_call_completed.value,
    }
)

# Error events captured so a failed run surfaces its real error message. The streaming
# error paths yield only these events -- the final run output is never yielded on failure.
_RUN_ERROR_EVENTS = frozenset({RunEvent.run_error.value, TeamRunEvent.run_error.value})


async def _report_progress(ctx: Context, progress: float, message: str, total: Optional[float] = None) -> None:
    """Send a progress notification; a failure here must never break the run.

    FastMCP no-ops when the client did not send a progressToken, so this is safe to
    call unconditionally.
    """
    try:
        await ctx.report_progress(progress=progress, total=total, message=message)
    except Exception:
        logger.debug("Failed to send MCP progress notification", exc_info=True)


def _describe_tool_call_event(event: Any) -> str:
    tool = getattr(event, "tool", None)
    tool_name = getattr(tool, "tool_name", None) or "tool"
    verb = "started" if str(getattr(event, "event", "")).endswith("Started") else "completed"
    return f"Tool call {verb}: {tool_name}"


async def _consume_agentic_stream(ctx: Context, stream: Any, label: str) -> Union[RunOutput, TeamRunOutput]:
    """Drive a streaming agent/team run and return its final output.

    The stream must be created with ``stream=True, stream_events=True,
    yield_run_output=True`` so tool-call events can be forwarded as progress
    notifications and the final ``RunOutput`` / ``TeamRunOutput`` arrives as the
    last yielded item. On failure the stream yields only a run-error event -- its
    message is captured so the client sees the real error, not a generic one.
    """
    final: Optional[Union[RunOutput, TeamRunOutput]] = None
    error_message: Optional[str] = None
    ticks = 0
    await _report_progress(ctx, 0.0, f"{label} started")
    async for item in stream:
        if isinstance(item, (RunOutput, TeamRunOutput)):
            final = item
            continue
        event = getattr(item, "event", None)
        if event in _TOOL_CALL_PROGRESS_EVENTS:
            ticks += 1
            await _report_progress(ctx, float(ticks), _describe_tool_call_event(item))
        elif event in _RUN_ERROR_EVENTS:
            error_message = getattr(item, "content", None) or "Run failed"
    if final is None:
        raise Exception(
            str(error_message) if error_message else f"{label} finished without producing a final run output"
        )
    return final


@contextmanager
def _detached_trace_context() -> Iterator[None]:
    """Run a component in a fresh OTel root trace, detached from FastMCP's tool-call span.

    FastMCP wraps every tool call in an identity-less ``tools/call ...`` SERVER span. Left
    attached, the agno run span nests under it, and the trace layer -- which reads a trace's
    identity (run_id / session_id / user_id / agent_id) from its root span -- takes it from
    that context-less protocol span instead of the run, so runs invoked over MCP land with a
    NULL, mislabeled trace. Detaching to an invalid parent makes the run span its own root,
    so the run is attributed exactly like the REST run routes (which have no wrapping span).

    No-op when OpenTelemetry is not installed.
    """
    try:
        from opentelemetry import context as otel_context  # type: ignore
        from opentelemetry import trace as otel_trace  # type: ignore
    except ImportError:
        yield
        return

    token = otel_context.attach(otel_trace.set_span_in_context(otel_trace.INVALID_SPAN))
    try:
        yield
    finally:
        otel_context.detach(token)


async def _run_agentic_component(
    ctx: Context, component: Any, message: str, user_id: Optional[str], session_id: Optional[str], label: str
) -> Union[RunOutput, TeamRunOutput]:
    """Shared run path for agents and teams: stream with progress for native components,
    plain await for everything else.

    Only native ``Agent`` / ``Team`` instances take the streaming path: remotes proxy to
    another AgentOS over HTTP and ``AgentProtocol`` implementations follow the protocol's
    streaming contract -- in both cases the streaming ``arun`` never yields the final
    output object, so they run non-streaming (no intermediate progress, same result
    contract).
    """
    from agno.agent.agent import Agent
    from agno.team.team import Team

    with _detached_trace_context():
        if not isinstance(component, (Agent, Team)):
            # Forward the caller's bearer token to Remote* proxies (as the REST routers
            # do) so a protected downstream AgentOS accepts the run; duck-typed protocol
            # implementations do not take auth_token, so only pass it to BaseRemote.
            extra = {"auth_token": _forwarded_auth_token()} if isinstance(component, BaseRemote) else {}
            return await component.arun(message, user_id=user_id, session_id=session_id, **extra)

        stream = component.arun(
            message,
            user_id=user_id,
            session_id=session_id,
            stream=True,
            stream_events=True,
            yield_run_output=True,
        )
        return await _consume_agentic_stream(ctx, stream, label=label)


def _describe_step_event(event: Any, total_steps: Optional[float]) -> str:
    verb = "started" if str(getattr(event, "event", "")).endswith("Started") else "completed"
    step_name = getattr(event, "step_name", None) or "step"
    step_index = getattr(event, "step_index", None)
    if isinstance(step_index, tuple) and step_index and isinstance(step_index[0], int):
        step_index = step_index[0]
    if isinstance(step_index, int) and total_steps:
        return f"Step {verb}: {step_name} ({step_index + 1}/{int(total_steps)})"
    return f"Step {verb}: {step_name}"


async def _consume_workflow_stream(
    ctx: Context,
    workflow: Any,
    stream: Any,
    total_steps: Optional[float],
    user_id: Optional[str],
) -> WorkflowRunOutput:
    """Drive a streaming workflow run and return its final output.

    Workflow streams do not support ``yield_run_output``. Completed runs carry the
    full ``WorkflowRunOutput`` on the terminal event; paused / cancelled / step-error
    runs end the stream with NO workflow-level terminal event, so the persisted run
    is fetched back via ``workflow.aget_run_output`` -- the same source of truth the
    REST router uses. Events from nested workflows (``nested_depth > 0``) are skipped:
    terminal handling and progress apply to the outer run only, and a nested failure
    the outer workflow recovers from must not abort it.

    Progress values are a plain monotonic counter (the MCP spec requires each
    notification's progress to increase); the step k/n detail lives in the message.
    """
    from agno.run.workflow import BaseWorkflowRunOutputEvent

    final: Optional[WorkflowRunOutput] = None
    error_message: Optional[str] = None
    run_id: Optional[str] = None
    session_id: Optional[str] = None
    ticks = 0.0
    await _report_progress(ctx, 0.0, "Workflow started")
    async for item in stream:
        if isinstance(item, WorkflowRunOutput):
            final = item
            continue
        if getattr(item, "nested_depth", 0):
            continue
        if isinstance(item, BaseWorkflowRunOutputEvent):
            run_id = getattr(item, "run_id", None) or run_id
            session_id = getattr(item, "session_id", None) or session_id
        event = getattr(item, "event", None)
        if event in (WorkflowRunEvent.step_started.value, WorkflowRunEvent.step_completed.value):
            ticks += 1.0
            await _report_progress(ctx, ticks, _describe_step_event(item, total_steps))
        elif event == WorkflowRunEvent.workflow_completed.value:
            final = getattr(item, "run_output", None) or final
        elif event == WorkflowRunEvent.workflow_error.value:
            # Do not raise mid-stream: closing the generator here would skip the
            # workflow's own error-status persistence. Capture and settle after.
            error_message = getattr(item, "error", None) or "Workflow run failed"
    if final is None and run_id is not None:
        try:
            final = await workflow.aget_run_output(run_id=run_id, session_id=session_id, user_id=user_id)
        except Exception:
            logger.debug("Could not fetch persisted workflow run %s after stream end", run_id, exc_info=True)
    if final is None:
        raise Exception(
            str(error_message) if error_message else "Workflow run finished without producing a final run output"
        )
    return final


def _http_request_or_none() -> Optional[Any]:
    """The in-flight Starlette request, or None when there is none (e.g. stdio transport)."""
    from fastmcp.server.dependencies import get_http_request

    try:
        return get_http_request()
    except RuntimeError:
        return None


async def _assert_session_writable_mcp(
    os_app, component, session_id: str, user_id: Optional[str], session_type
) -> None:
    """Refuse an MCP run into a session owned by another user.

    Same rule the REST run routes apply. MCP tools surface plain exceptions, so the
    helper's HTTPException is mapped here: an unmapped one would reach the client as an
    opaque internal error.
    """
    from fastapi import HTTPException

    from agno.os.middleware.user_scope import assert_session_writable, caller_is_admin

    request = _http_request_or_none()
    # No in-flight request (e.g. stdio transport) means no scopes to read, so no admin.
    is_admin = caller_is_admin(request) if request is not None else False
    try:
        await assert_session_writable(
            getattr(component, "db", None) or os_app.db,
            session_id,
            user_id or getattr(component, "user_id", None),
            session_type=session_type,
            is_admin=is_admin,
        )
    except HTTPException as e:
        raise Exception(e.detail if isinstance(e.detail, str) else str(e.detail))


def _session_id_or_new(session_id: Optional[str]) -> str:
    """Return the caller's session_id, or mint a fresh one when it is omitted.

    The run tools must not forward ``session_id=None`` to ``arun``: a component that is
    reused across calls -- a shared ``AgentProtocol``/``RemoteAgent``/``RemoteTeam``, a
    remote workflow, or any instance not deep-copied per call -- would fall back to the
    sticky per-instance session that ``initialize_session`` caches on it, collapsing every
    "sessionless" run into one ever-growing conversation and leaking history between
    unrelated requests. The REST run routes mint a uuid per run for exactly this reason
    (see ``routers/agents/router.py``); the MCP run tools do the same so the documented
    contract -- "omit session_id to start a new one" -- holds regardless of how the
    component was resolved. An explicit session_id is always honoured, so continuing a
    conversation still works.
    """
    if session_id is None or session_id == "":
        return str(uuid4())
    return session_id


def _classify_lifecycle_target(
    agent_id: Optional[str], team_id: Optional[str], workflow_id: Optional[str]
) -> "tuple[Literal['agents', 'teams', 'workflows'], str]":
    """Map the exactly-one component id to its (type, id), without resolving it.

    Kept separate from resolution so the scope gate runs before we deep-copy or invoke a
    factory for the target.
    """
    provided = [
        (kind, cid) for kind, cid in (("agents", agent_id), ("teams", team_id), ("workflows", workflow_id)) if cid
    ]
    if len(provided) != 1:
        raise Exception("Provide exactly one of agent_id, team_id, or workflow_id")
    return provided[0]  # type: ignore[return-value]


async def _resolve_run_component(
    os: "AgentOS",
    kind: "Literal['agents', 'teams', 'workflows']",
    component_id: str,
    *,
    user_id: Optional[str],
    session_id: Optional[str],
    strict: bool = True,
    version: Optional[int] = None,
    published_only: bool = True,
) -> Any:
    """Resolve a component for a run/lifecycle tool exactly as the REST routes do.

    Delegates to the shared ``resolve_agent`` / ``resolve_team`` / ``resolve_workflow``
    helpers so the MCP surface matches REST on all three axes the low-level lookup
    otherwise dropped:

    - ``create_fresh=True`` (via the resolvers): each run gets a ``deep_copy()`` instead of
      the shared singleton, so concurrent MCP runs cannot contaminate each other's state.
    - ``db=os.db, registry=os.registry``: components registered in the DB registry (not the
      in-memory list) resolve and run, just like over REST.
    - factory ``RequestContext`` built from the in-flight HTTP request, so ``AgentFactory``
      entries resolve instead of raising.

    ``version``/``published_only`` mirror the REST lifecycle routes: continue/cancel
    resolve with ``published_only=False`` (the run may live on a draft-only preview
    component), and an explicit ``version`` re-resolves a run at its stamped version.
    The resolvers apply the draft-preview gate (``allow_draft_preview``) for an
    explicit version using the in-flight HTTP request's identity, identically to REST.

    The resolvers raise ``HTTPException``; MCP tools surface plain exceptions, so map it.
    """
    from fastapi import HTTPException

    request = _http_request_or_none()
    try:
        if kind == "agents":
            return await resolve_agent(
                component_id,
                os.agents,
                os.db,
                os.registry,
                version=version,
                request=request,
                user_id=user_id,
                session_id=session_id,
                strict=strict,
                published_only=published_only,
            )
        if kind == "teams":
            return await resolve_team(
                component_id,
                os.teams,
                db=os.db,
                registry=os.registry,
                version=version,
                request=request,
                user_id=user_id,
                session_id=session_id,
                strict=strict,
                published_only=published_only,
            )
        return await resolve_workflow(
            component_id,
            os.workflows,
            db=os.db,
            registry=os.registry,
            version=version,
            request=request,
            user_id=user_id,
            session_id=session_id,
            strict=strict,
            published_only=published_only,
        )
    except HTTPException as e:
        # Keep the id in the not-found message (the resolvers say only "Agent not found"),
        # matching the pre-v2.7 MCP error text and giving the client the id it passed.
        if e.status_code == 404:
            singular = {"agents": "Agent", "teams": "Team", "workflows": "Workflow"}[kind]
            raise Exception(f"{singular} {component_id} not found")
        raise Exception(e.detail if isinstance(e.detail, str) else str(e.detail))


def _make_run_ownership_verifier(os: "AgentOS"):
    """Bind the run-lifecycle ownership verifier to an AgentOS.

    continue_run and cancel_run must not let a caller reach a DIFFERENT component's run
    by passing its run_id while naming a component they may reach. Two tiers, matching
    the REST cancel/continue routes:

    - A scoped (user-isolation) caller must own the session the run lives in:
      session_id is required and an absent session or run row fails closed, exactly
      the REST scoped-caller rule.
    - An admin / non-isolated caller is gated by the persisted run row itself, looked
      up by run_id alone (a caller-supplied session_id cannot steer the check): a row
      bound to a different component is refused; an absent row proceeds, because an
      in-flight or not-yet-started run has no row until it pauses or finishes and
      cancellation intent exists precisely for those runs. REST admin callers get no
      ownership check at all, so this tier is strictly harder than REST while keeping
      every REST-cancellable run cancellable here too.
    """

    async def verify(
        component: Any,
        component_type: Literal["agents", "teams", "workflows"],
        component_id: str,
        session_id: Optional[str],
        run_id: str,
    ):
        if component is None:
            raise Exception(f"Component {component_id} not found")
        scoped_user_id = _scoped_caller_user_id()
        if isinstance(component, BaseRemote):
            # Remote components keep their sessions on the remote OS: there is no local
            # session to prove the binding against (BaseRemote has no aget_session), and
            # the forwarded call would not carry this caller's identity for the remote
            # to check either. A scoped caller fails closed; an admin / non-isolated
            # deployment proceeds and the downstream OS owns the run.
            if scoped_user_id is not None:
                raise Exception(
                    "Run ownership cannot be verified for remote components; an administrator can act on this run."
                )
            return
        if scoped_user_id is not None:
            # Scoped caller: per-user session ownership, fail-closed (the REST rule).
            if not session_id:
                raise Exception("session_id is required to act on this run")
            try:
                await session_service.verify_run_ownership(
                    component,
                    session_id=session_id,
                    run_id=run_id,
                    user_id=scoped_user_id,
                    component_type=component_type,
                    component_id=component_id,
                )
            except session_service.RunOwnershipError as e:
                raise Exception(str(e))
            return
        # Admin / non-isolated caller: refuse only a run row that provably belongs to a
        # different component. The row lookup keys on run_id -- the one value the caller
        # must supply truthfully, since it names the run they want to act on.
        try:
            await session_service.verify_persisted_run_binding(
                getattr(component, "db", None) or os.db,
                run_id=run_id,
                component_type=component_type,
                component_id=component_id,
            )
        except session_service.RunOwnershipError as e:
            raise Exception(str(e))

    return verify


async def _verify_factory_run_ownership(
    db: Any,
    component_type: Literal["agents", "teams", "workflows"],
    component_id: str,
    session_id: Optional[str],
    run_id: str,
) -> None:
    """The run-ownership gate for a FACTORY component, without building the factory.

    A factory has no resolved instance (and no ``aget_session``), so the two tiers run
    off its ``db`` directly -- the same shape the REST factory-cancel routes use. Scoped:
    session ownership via ``verify_run_in_session_via_db``; admin / non-isolated: the
    persisted-run binding by run_id. Mirrors ``_make_run_ownership_verifier``'s local
    tiers exactly, only db-based.
    """
    from fastapi import HTTPException

    from agno.os.middleware.user_scope import verify_run_in_session_via_db

    scoped_user_id = _scoped_caller_user_id()
    if scoped_user_id is not None:
        if not session_id:
            raise Exception("session_id is required to act on this run")
        try:
            await verify_run_in_session_via_db(
                db, session_id, run_id, scoped_user_id, component_type=component_type, component_id=component_id
            )
        except HTTPException as e:
            raise Exception(e.detail if isinstance(e.detail, str) else str(e.detail))
        return
    try:
        await session_service.verify_persisted_run_binding(
            db, run_id=run_id, component_type=component_type, component_id=component_id
        )
    except session_service.RunOwnershipError as e:
        raise Exception(str(e))


async def _static_cancel_factory_run(component_type: Literal["agents", "teams", "workflows"], run_id: str) -> None:
    """Record cancellation intent for a factory run by run_id, building no component.

    Cancellation is a global-registry intent keyed on run_id (plus a queue tombstone for
    a still-queued ticket), so it never needs a component instance -- the REST
    factory-cancel routes cancel statically for exactly this reason. Building the factory
    here (as generic run resolution does) would 400 a required-input factory or a
    request-less transport, making a live factory run uncancellable over MCP.
    """
    from agno.os.job_queue import get_active_queue_worker

    queue_worker = get_active_queue_worker()
    if queue_worker is not None:
        await queue_worker.acancel_queued(run_id)
    if component_type == "agents":
        from agno.agent._run import acancel_run as _acancel
    elif component_type == "teams":
        from agno.team._run import acancel_run as _acancel
    else:
        from agno.run.cancel import acancel_run as _acancel
    await _acancel(run_id)


# ==================== Exposed components (agents/teams/workflows as tools) ====================

# An exposed tool is named by its component id VERBATIM -- the id is also the client's
# handle for continue_run/get_sessions and the resource segment in per-resource scopes
# (agents:<id>:run), so a name that differs from the id would break HITL resume and make
# the visible tool name disagree with the scope that grants it. Ids outside this shape
# are therefore a hard error, never sanitized. The shape is what the LLM providers MCP
# clients bridge tool names into actually accept (probed live against OpenAI, Anthropic,
# and Gemini, 2026-08): at most 128 characters, starting with a letter or underscore --
# Gemini 400s a leading digit, and it validates per request, so ONE bad name takes down
# every tool in the call. A violating name would fail client-side at runtime with no
# server signal, which is why it is rejected at build instead.
_TOOL_NAME_MAX_LENGTH = 128
_TOOL_NAME_VALID_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")

# One fixed sentence appended to every exposed tool's description: the session contract
# is part of the tool's calling convention, not something each component should restate.
_EXPOSED_SESSION_SENTENCE = (
    "Pass the returned session_id back to continue the conversation; omit it to start a new one."
)


def _safe_component_metadata(component: Any) -> "tuple[Optional[str], Optional[str]]":
    """``(name, description)`` without letting a remote component take down the build.

    On ``RemoteTeam``/``RemoteWorkflow`` these are network-backed properties (a
    synchronous config fetch); an unreachable remote at boot must degrade this tool's
    description to the id, not hard-fail ``get_app()`` -- REST included -- before
    anything called the component.
    """
    try:
        name = getattr(component, "name", None)
    except Exception:
        name = None
    try:
        description = getattr(component, "description", None)
    except Exception:
        description = None
    return name, description


def _suggest_exposed_id(component_id: str, singular: str, taken: Dict[str, str]) -> Optional[str]:
    """A clean candidate id to put in the invalid-id error, or None when no good one
    exists (e.g. a fully non-Latin id). Suggest, never apply: silently rewriting would
    decouple the tool name from the continue_run handle and the scope segment, and
    mutating a component's id at build could break persisted/registry identity."""
    import unicodedata

    # NFKD + ASCII fold transliterates accents (réviseur -> reviseur) instead of
    # deleting them; the house id mint then lowercases and collapses separator runs.
    ascii_id = unicodedata.normalize("NFKD", component_id).encode("ascii", "ignore").decode("ascii")
    candidate = generate_component_id_from_name(ascii_id) if ascii_id.strip() else ""
    candidate = re.sub(r"-{2,}", "-", re.sub(r"[^A-Za-z0-9_-]+", "-", candidate)).strip("-")
    if candidate and not re.match(r"[A-Za-z_]", candidate):
        candidate = f"{singular}-{candidate}"
    if not candidate or candidate in taken or not _TOOL_NAME_VALID_RE.fullmatch(candidate):
        return None
    if len(candidate) > _TOOL_NAME_MAX_LENGTH:
        return None
    return candidate


def _validate_exposed_tool_name(
    value: str,
    singular: str,
    component_name: Optional[str],
    taken: Dict[str, str],
    source: str = "id",
) -> str:
    """The exposed tool name -- the component id, or an ``as_tool(name=...)`` override
    -- validated verbatim, never sanitized.

    ``fullmatch`` (not ``match``): ``$`` would accept a trailing newline.
    """
    shape_rule = (
        "tool names must start with a letter or underscore and contain only letters, digits, "
        "hyphens, and underscores (Gemini rejects a leading digit, and one invalid name fails "
        "every tool in the request)"
    )
    if not _TOOL_NAME_VALID_RE.fullmatch(value):
        candidate = _suggest_exposed_id(value, singular, taken)
        if source == "as_tool":
            advice = f" For example, name={candidate!r}." if candidate else ""
            raise ValueError(f"as_tool(name={value!r}) is not a valid tool name: {shape_rule}.{advice}")
        # Say where the id came from: with no explicit id= the user only ever typed
        # name=..., so an error quoting the derived id alone sends them hunting for a
        # string that is not in their source.
        origin = ""
        if component_name and generate_id_from_name(component_name) == value:
            origin = f" (auto-derived from name={component_name!r})"
        advice = (
            f" For example, set id={candidate!r} on the component, or publish it under a different "
            f"tool name via as_tool(name={candidate!r})."
            if candidate
            else " Set an id on the component using letters, digits, hyphens, or underscores, starting with a letter or underscore -- or publish it under a valid tool name via as_tool(name=...)."
        )
        raise ValueError(
            f"MCPConfig cannot expose {singular} id {value!r}{origin}: a bare component's tool name is "
            f"its id verbatim, and {shape_rule}.{advice} Note: changing the id of a component that "
            "already has sessions is a migration -- sessions and memories are keyed by it."
        )
    if len(value) > _TOOL_NAME_MAX_LENGTH:
        where = "as_tool(name=...)" if source == "as_tool" else f"{singular} id"
        raise ValueError(
            f'MCP tool name "{value}" (from {where}) is {len(value)} characters; the LLM providers '
            f"MCP clients bridge tools into cap tool names at {_TOOL_NAME_MAX_LENGTH} characters "
            "(OpenAI, Anthropic, and Gemini all reject longer). Use a shorter name."
        )
    return value


def _locate_component(entry: Any, os: "AgentOS", expected_kind: "Optional[str]" = None) -> "tuple[str, Any]":
    """``(kind, component)`` for an exposure entry, derived from roster membership.

    Exposure is a view on the deployment, not a second registration path: sessions,
    config, REST, and MCP must agree on what exists, so every exposed component must be
    part of the roster -- and the roster a component lives in IS its kind (``Remote*``
    classes are not subclasses of Agent/Team, so isinstance cannot tell kinds apart).
    Identity match first; then id equality, so an equal copy of a roster component
    still resolves -- but an id present in more than one roster is ambiguous and
    errors, because publishing the wrong same-id component under another kind's scopes
    is exactly the silent failure this check exists to prevent.

    ``expected_kind`` restricts the id fallback for entries whose class already names
    their kind (concrete components, ``Remote*``, factories): a non-roster ``Agent``
    or ``RemoteAgent`` entry must never resolve to a same-id roster ``Team`` -- that
    would run the team under the agent entry's name and description, gated by the
    other kind's scopes. Only a truly kindless duck-typed protocol object keeps the
    all-roster scan.
    """
    for kind in ("agents", "teams", "workflows"):
        for component in getattr(os, kind, None) or []:
            if component is entry:
                # A concrete-class entry names its kind: if it was placed in the wrong
                # roster (a Team in agents=, violating the annotation), running it under
                # that roster's scopes and SessionType would be silently wrong. Refuse
                # instead -- roster placement and class must agree.
                if expected_kind is not None and kind != expected_kind:
                    raise ValueError(
                        f"MCPConfig.tools entry {getattr(entry, 'id', None)!r} is a {expected_kind[:-1]} "
                        f"by type but is registered in AgentOS({kind}=[...]); place it in the roster "
                        f"matching its type so its scopes and session semantics are correct."
                    )
                return kind, component
    entry_id = getattr(entry, "id", None)
    if entry_id is not None:
        matches = []
        for kind in (expected_kind,) if expected_kind else ("agents", "teams", "workflows"):
            for component in getattr(os, kind, None) or []:
                if getattr(component, "id", None) == entry_id:
                    matches.append((kind, component))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            kinds = " and ".join(kind for kind, _ in matches)
            raise ValueError(
                f"MCPConfig.tools entry with id {entry_id!r} matches components in more than one "
                f"AgentOS roster ({kinds}); pass the roster instance itself so the kind is unambiguous."
            )
        if expected_kind:
            other_kinds = [
                kind
                for kind in ("agents", "teams", "workflows")
                if kind != expected_kind
                and any(getattr(c, "id", None) == entry_id for c in getattr(os, kind, None) or [])
            ]
            if other_kinds:
                singular = {"agents": "agent", "teams": "team", "workflows": "workflow"}[expected_kind]
                article = "an" if singular == "agent" else "a"
                raise ValueError(
                    f"MCPConfig.tools contains {article} {singular} with id {entry_id!r} that is not in "
                    f"AgentOS({expected_kind}=[...]); the roster component with that id is of a different "
                    f"kind ({' and '.join(other_kinds)}). If you meant that component, pass the roster "
                    "instance itself -- exposing it through a same-id entry of another kind would swap "
                    "which component runs and which scopes gate it."
                )
    name, _ = _safe_component_metadata(entry)
    label = name or entry_id or type(entry).__name__
    raise ValueError(
        f"MCPConfig.tools contains {label!r} which is not part of the AgentOS roster; add it to "
        f"AgentOS(agents=[...]/teams=[...]/workflows=[...]) or remove it from MCPConfig.tools."
    )


def _split_tool_entries(mcp_config: "Optional[MCPConfig]", os: "AgentOS") -> "tuple[List[Any], List[tuple]]":
    """Classify ``MCPConfig.tools`` into custom-tool entries and component exposures.

    Exposures come back as ``(kind, component, marker)``, where ``marker`` is the
    ``as_tool(...)`` marker carrying the model-facing overrides, or ``None`` for a bare
    component that takes all of its presentation from itself.
    A bare Agent/Team/Workflow that is not in the roster is a hard error here (it would
    otherwise fall through to the custom-tool TypeError, which names the type but not
    the fix); non-component callables pass through untouched.
    """
    from agno.agent.agent import Agent
    from agno.team.team import Team
    from agno.tools.component import ComponentTool
    from agno.tools.toolkit import Toolkit
    from agno.workflow.workflow import Workflow

    def _concrete_kind(obj: Any) -> "Optional[str]":
        # The class names the intended kind, so _locate_component can refuse a same-id
        # roster component of another kind instead of silently publishing it. Remote*
        # and factory classes name their kind just as the concrete components do; only
        # a truly kindless duck-typed protocol object returns None (kind comes from
        # the roster alone).
        from agno.agent.factory import AgentFactory
        from agno.agent.remote import RemoteAgent
        from agno.agents.base import BaseExternalAgent
        from agno.team.factory import TeamFactory
        from agno.team.remote import RemoteTeam
        from agno.workflow.factory import WorkflowFactory
        from agno.workflow.remote import RemoteWorkflow

        kinds: "tuple[tuple[type, str], ...]" = (
            (Agent, "agents"),
            (RemoteAgent, "agents"),
            (AgentFactory, "agents"),
            (BaseExternalAgent, "agents"),
            (Team, "teams"),
            (RemoteTeam, "teams"),
            (TeamFactory, "teams"),
            (Workflow, "workflows"),
            (RemoteWorkflow, "workflows"),
            (WorkflowFactory, "workflows"),
        )
        for cls, kind in kinds:
            if isinstance(obj, cls):
                return kind
        return None

    def _roster_member(obj: Any) -> bool:
        return any(
            obj is component for kind in ("agents", "teams", "workflows") for component in getattr(os, kind, None) or []
        )

    customs: List[Any] = []
    exposures: List[tuple] = []
    for entry in getattr(mcp_config, "tools", None) or []:
        if isinstance(entry, ComponentTool):
            kind, component = _locate_component(entry.component, os, expected_kind=_concrete_kind(entry.component))
            exposures.append((kind, component, entry))
            continue
        if isinstance(entry, str):
            raise TypeError(
                f"MCPConfig.tools got the string {entry!r}; pass the component instance itself "
                "(or a callable/Agno tool)."
            )
        if isinstance(entry, Toolkit):
            # Classified by type, not left to the heuristics below. A Toolkit carries an
            # id like a component does, so a subclass that also defines ``arun`` would
            # otherwise be read as an off-roster component and rejected as missing from
            # a roster it was never meant to join.
            customs.append(entry)
            continue
        if isinstance(entry, (Agent, Team, Workflow)):
            kind, component = _locate_component(entry, os, expected_kind=_concrete_kind(entry))
            exposures.append((kind, component, None))
            continue
        # Anything that lives on the roster is a component entry, whatever its shape:
        # Remote* instances, component factories (BaseFactory has no arun and is not
        # callable), and duck-typed protocol implementations. Classifying a roster
        # factory as a custom tool would hand Tool.from_function an object that is not
        # a tool at all.
        if _roster_member(entry):
            kind, component = _locate_component(entry, os, expected_kind=_concrete_kind(entry))
            exposures.append((kind, component, None))
            continue
        # Off-roster component-shaped entries (id + arun, not a callable tool) resolve
        # through the roster too -- reaching an equal-id roster component, the
        # wrong-kind error, or the not-in-roster error, never the custom-tool TypeError.
        if not callable(getattr(entry, "entrypoint", None)) and not callable(entry):
            if getattr(entry, "id", None) is not None and hasattr(entry, "arun"):
                kind, component = _locate_component(entry, os, expected_kind=_concrete_kind(entry))
                exposures.append((kind, component, None))
                continue
        customs.append(entry)
    return customs, exposures


def _make_exposed_run_tool(
    os: "AgentOS",
    kind: "Literal['agents', 'teams']",
    component_id: str,
    result_mode: str,
    continue_run_available: bool = True,
) -> Callable:
    """A run tool bound to one agent or team: the ``run_agent``/``run_team`` body with
    the component id fixed. Resolution happens at call time so per-run copies, registry
    lookup, versioning, and factories behave identically to the generic tools."""
    session_type = SessionType.AGENT if kind == "agents" else SessionType.TEAM
    label_prefix = "Agent" if kind == "agents" else "Team"

    async def run_exposed(
        message: str,
        ctx: Context,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> ToolResult:
        _require_tool_scopes("POST", f"/{kind}/{component_id}/runs")
        resolved_user_id = _resolve_user_id(user_id)
        component = await _resolve_run_component(
            os, kind, component_id, user_id=resolved_user_id, session_id=session_id
        )
        # Mint a fresh session per call when omitted (matches REST), never the sticky default.
        new_session_id = _session_id_or_new(session_id)
        await _assert_session_writable_mcp(os, component, new_session_id, resolved_user_id, session_type)
        # Label from the resolved component, matching run_agent/run_team -- a registry or
        # published version may carry a different name than the roster instance. Safe
        # read: on a remote component the name is a network-backed property.
        resolved_name, _ = _safe_component_metadata(component)
        run_output = await _run_agentic_component(
            ctx,
            component,
            message,
            resolved_user_id,
            new_session_id,
            label=f"{label_prefix} {resolved_name or component_id}",
        )
        return build_run_tool_result(run_output, result_mode, continue_run_available=continue_run_available)

    return run_exposed


def _make_exposed_workflow_tool(
    os: "AgentOS",
    component_id: str,
    result_mode: str,
    continue_run_available: bool = True,
) -> Callable:
    """A run tool bound to one workflow: the ``run_workflow`` body with the id fixed."""

    async def run_exposed_workflow(
        message: str,
        ctx: Context,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> ToolResult:
        from agno.workflow.remote import RemoteWorkflow

        _require_tool_scopes("POST", f"/workflows/{component_id}/runs")
        resolved_user_id = _resolve_user_id(user_id)
        workflow = await _resolve_run_component(
            os, "workflows", component_id, user_id=resolved_user_id, session_id=session_id
        )
        # Mint a fresh session per call when omitted (matches REST), never the sticky default.
        new_session_id = _session_id_or_new(session_id)
        await _assert_session_writable_mcp(os, workflow, new_session_id, resolved_user_id, SessionType.WORKFLOW)
        # Detach from FastMCP's tool-call span so the workflow run is its own root trace.
        with _detached_trace_context():
            if isinstance(workflow, RemoteWorkflow):
                run_output = await workflow.arun(
                    message, user_id=resolved_user_id, session_id=new_session_id, auth_token=_forwarded_auth_token()
                )
                return build_run_tool_result(run_output, result_mode, continue_run_available=continue_run_available)
            steps = getattr(workflow, "steps", None)
            total_steps = float(len(steps)) if isinstance(steps, (list, tuple)) and steps else None
            stream = workflow.arun(
                message,
                user_id=resolved_user_id,
                session_id=new_session_id,
                stream=True,
                stream_events=True,
            )
            run_output = await _consume_workflow_stream(ctx, workflow, stream, total_steps, resolved_user_id)
        return build_run_tool_result(run_output, result_mode, continue_run_available=continue_run_available)

    return run_exposed_workflow


def _register_exposed_components(
    mcp: FastMCP,
    os: "AgentOS",
    result_mode: str,
    custom_tool_names: "Optional[Dict[str, str]]" = None,
    exposure_entries: "Optional[List[tuple]]" = None,
    enabled_tags: "Optional[set]" = None,
) -> None:
    """Register the component entries from ``MCPConfig.tools`` as named tools.

    ``exposure_entries`` come from ``_split_tool_entries``: ``(kind, component,
    marker)``, where ``marker`` is the ``as_tool(...)`` marker carrying the
    explicit model-facing overrides, or ``None`` for a bare component -- which gets its
    id as the tool name and its own description and name. Names are validated verbatim,
    never sanitized;
    collisions with the enabled default tools, custom tools, or other exposed
    components are a hard error at build. The component id (not the tool name) remains
    the continue_run handle -- carried in the result's structuredContent -- and the
    per-resource scope segment.

    The registered tool list is deliberately static and identical for every caller:
    exposure is a hand-typed publication list, so listing a tool's name and description
    is what the deployer asked for, and access is enforced at call time via the same
    scope checks the generic run tools apply. (The MCP spec does permit per-caller
    tool lists; serving one is a possible future refinement, not a spec constraint.)
    """
    if not exposure_entries:
        return

    # Names already claimed by the default tools that will actually register, and by
    # the custom tools registered just before this (their REAL registered names, so
    # e.g. a functools.partial custom tool named "partial" by FastMCP still collides).
    enabled_tags = enabled_tags if enabled_tags is not None else set()
    taken: Dict[str, str] = {
        name: f'the default tool "{name}"' for name, tags in _BUILTIN_TOOL_NAMES.items() if tags & enabled_tags
    }
    taken.update(custom_tool_names or {})

    # continue_run rides along with exposure by default (the lifecycle tag), so this is
    # False only when the deployer opted out -- the paused-result text then points the
    # caller at REST instead of at a tool that does not exist.
    continue_run_available = bool({"core", "lifecycle"} & enabled_tags)
    singulars = {"agents": "agent", "teams": "team", "workflows": "workflow"}

    for kind, component, marker in exposure_entries:
        name_override = marker.name if marker is not None else None
        description_override = marker.description if marker is not None else None
        title_override = marker.title if marker is not None else None
        annotations_override = marker.annotations if marker is not None else None
        singular = singulars[kind]
        # AgentOS mints ids for roster components at construction (name-derived when
        # named, generated otherwise), so the id is normally always set here; the
        # error is defense for exotic components that dodge that path.
        component_id = getattr(component, "id", None)
        # On Remote* components name/description are network-backed properties (a
        # synchronous config fetch that blocks to the timeout when the remote is
        # unreachable). Skip the read for those when both overrides are supplied and
        # non-blank -- neither the tool name nor the description needs the component's
        # own metadata then. The bare path (no name override) still needs the name for
        # the auto-derived-id origin hint; a blank description override still needs the
        # component description as its fallback. A LOCAL component's metadata is a
        # plain attribute read, so it is never skipped: the display title falls back to
        # the component's name, which the skip would otherwise throw away.
        if isinstance(component, BaseRemote) and name_override is not None and (description_override or "").strip():
            component_name, component_description = None, None
        else:
            component_name, component_description = _safe_component_metadata(component)
        if not component_id:
            # Type name, never repr(): a component repr can carry credentials (a
            # model api_key) into the error message.
            label = component_name or type(component).__name__
            raise ValueError(
                f"MCPConfig.tools contains {label!r} which has no id; set id= on the "
                f"component so its MCP tool has a stable name."
            )
        if name_override is not None:
            tool_name = _validate_exposed_tool_name(name_override, singular, None, taken, source="as_tool")
            # The override renames the TOOL, but the component id is still the
            # per-resource scope segment (``agents:<id>:run``), the continue_run handle,
            # and the session key. A slash or other out-of-charset id would make the
            # synthetic scope path (``/agents/<id>/runs``) truncate at the first slash,
            # so ``agents:<prefix>:run`` would authorize a different component. The bare
            # path validates this as a side effect of validating the tool name; the
            # override path must check the id explicitly.
            if not _TOOL_NAME_VALID_RE.fullmatch(component_id):
                raise ValueError(
                    f"MCPConfig.tools exposes {singular} id {component_id!r} via as_tool(name={tool_name!r}), "
                    "but the id must still start with a letter or underscore and contain only "
                    "letters, digits, hyphens, and underscores: it is the RBAC scope segment "
                    f"(agents:<id>:run), the continue_run handle, and the session key. Set a "
                    "scope-safe id on the component (changing it is a migration -- sessions and "
                    "memories are keyed by it)."
                )
        else:
            tool_name = _validate_exposed_tool_name(component_id, singular, component_name, taken)
        if tool_name in taken:
            # Attribute the name to where the user actually typed it: an as_tool
            # override quoted as "the component id" sends them hunting the wrong string.
            source_label = (
                f'as_tool(name="{tool_name}") on {singular} "{component_id}"'
                if name_override is not None
                else f'{singular} id "{component_id}"'
            )
            # Advice must name a knob that actually frees the colliding name. The
            # lifecycle pair is tagged both "core" and "lifecycle": when it rode in via
            # the exposure (core not enabled) only the lifecycle switches free it, but
            # when core is enabled those switches do nothing (core keeps re-adding it),
            # so _collision_free_advice keys on HOW the name was claimed, not its tags.
            free_advice = _collision_free_advice(tool_name, enabled_tags)
            raise ValueError(
                f'MCP tool name "{tool_name}" (from {source_label}) collides with '
                f"{taken[tool_name]}. Rename the tool (as_tool(name=...)) or the component id, "
                f"{free_advice}so each tool name is unique."
            )
        taken[tool_name] = f'exposed {singular} "{component_id}"'

        display_name = component_name or component_id
        # strip() BEFORE the fallback test: a whitespace-only description is truthy
        # but would rstrip to nothing, yielding a description that starts with ".".
        base_description = (description_override or "").strip() or (component_description or "").strip()
        if not base_description:
            base_description = f"Run the {display_name} {singular} with a message."
        if not base_description.endswith((".", "!", "?")):
            base_description += "."
        description = f"{base_description} {_EXPOSED_SESSION_SENTENCE}"

        if kind == "workflows":
            fn = _make_exposed_workflow_tool(os, component_id, result_mode, continue_run_available)
        else:
            fn = _make_exposed_run_tool(os, kind, component_id, result_mode, continue_run_available)  # type: ignore[arg-type]
        # component_name is None on the skipped-metadata path above, so this fallback
        # never reaches for a Remote* component's network-backed name just to fill a
        # display title -- the tool name is the last resort instead.
        title, annotations = tool_presentation(
            title_override,
            annotations_override,
            defaults=_EXPOSED_COMPONENT_ANNOTATIONS,
            fallback_title=component_name or tool_name,
            source=f'as_tool(annotations=...) on {singular} "{component_id}"',
        )
        mcp.tool(name=tool_name, title=title, description=description, annotations=annotations)(fn)


def build_mcp_server(
    os: "AgentOS",
) -> FastMCP:
    """Build the FastMCP server for an AgentOS.

    Registers the built-in tools (scoped by ``os.mcp_config``) and any custom tools.
    Split out from :func:`get_mcp_server` so the tool surface can be exercised directly
    by an in-memory MCP client in tests, without the HTTP/JWT layer.
    """
    mcp_config: "Optional[MCPConfig]" = getattr(os, "mcp_config", None)

    # Create an MCP server. With AgentOS(mcp_auth=...) set, the resolved fastmcp provider
    # owns authentication for the HTTP transport: http_app() serves its discovery/OAuth
    # routes inside this app and wraps the MCP path in the SDK's challenge middleware.
    # The in-memory client path used in tests ignores it.
    mcp = FastMCP(os.name or "AgentOS", auth=os._get_mcp_auth_provider())

    # Classify the tool surface up front: the enabled default-tool tags depend on
    # whether components are exposed (the lifecycle pair rides along with exposure).
    custom_entries, exposure_entries = _split_tool_entries(mcp_config, os)
    enabled_tags = _enabled_builtin_tags(mcp_config, has_exposures=bool(exposure_entries))

    # Decorator used to register the built-in tools. Honors ``mcp_config`` scoping;
    # behaves exactly like ``mcp.tool`` when no config (or default config) is provided.
    register_builtin_tool = _builtin_tool_registrar(mcp, enabled_tags)

    # How the run tools serialize their results ("trimmed" keeps the frontend model's
    # context clean; "full" is the escape hatch for programmatic clients).
    result_mode = mcp_config.result_mode if mcp_config is not None else "trimmed"

    # Component resolution + ownership gate shared by continue_run and cancel_run.
    _verify_run_ownership = _make_run_ownership_verifier(os)

    # The ride-along pair is bounded to the publication list. When continue_run/
    # cancel_run would not register at all without exposures -- neither "core" (whose
    # generic run tools reach the whole roster anyway) nor "lifecycle" (an explicit
    # include under the default surface: the deployer chose a roster-wide resume
    # surface) is enabled on its own -- they must not reach components the deployer
    # chose not to publish: tools= bounds what can be started on this server AND what
    # can be resumed or cancelled. None means unrestricted (REST parity).
    tags_without_ride_along = _enabled_builtin_tags(mcp_config, has_exposures=False)
    lifecycle_rides_only = "lifecycle" in enabled_tags and not ({"core", "lifecycle"} & tags_without_ride_along)
    published_lifecycle_targets: "Optional[set]" = (
        {(kind, getattr(component, "id", None)) for kind, component, _ in exposure_entries}
        if lifecycle_rides_only
        else None
    )

    def _require_published_component(tool_name: str, component_type: str, component_id: str) -> None:
        """Fail closed when the riding pair is asked about an unpublished component.

        Without this, an exposure-only server (default_tools=False) would let any
        caller resume or cancel runs on EVERY roster component -- including resuming a
        paused confirmation-required tool on a component the deployer deliberately
        left off the surface. The publication list is public via tools/list, so this
        reveals nothing new."""
        if published_lifecycle_targets is None:
            return
        if (component_type, component_id) in published_lifecycle_targets:
            return
        singular = {"agents": "agent", "teams": "team", "workflows": "workflow"}.get(component_type, component_type)
        raise Exception(
            f"{tool_name} on this server only acts on runs of its published components; "
            f"{singular} {component_id!r} is not one of them. Use the REST API to manage "
            "other components' runs."
        )

    @register_builtin_tool(
        name="get_agentos_config",
        title="Get AgentOS Configuration",
        description=(
            "Discover this AgentOS: the agents, teams, and workflows available to run (with their ids "
            "and descriptions), and the database ids used by the session tools. Call this first to learn "
            "what you can operate. The payload is deliberately compact -- the full configuration lives on "
            "the REST /config endpoint."
        ),
        tags={"core"},
        annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )  # type: ignore
    async def config() -> Dict[str, Any]:
        _require_tool_scopes("GET", "/config")
        from agno.db.base import BaseDb

        request = _http_request_or_none()
        # Filter the roster to the caller's per-resource scopes, exactly as the REST list
        # routes do -- but only when authorization is enforced (open/dev instances and
        # unscoped tokens see everything). A caller scoped to one agent must not be able to
        # enumerate the whole deployment here when it cannot over GET /agents.
        authorization_enabled = bool(getattr(getattr(request, "state", None), "authorization_enabled", False))

        def _accessible(resources: Any, resource_type: str) -> List[Any]:
            items = list(resources or [])
            if authorization_enabled and request is not None and items:
                from agno.os.auth import filter_resources_by_access

                return filter_resources_by_access(request, items, resource_type)
            return items

        agents_out = [AgentSummaryResponse.from_agent(a).model_dump() for a in _accessible(os.agents, "agents")]
        teams_out = [TeamSummaryResponse.from_team(t).model_dump() for t in _accessible(os.teams, "teams")]
        workflows_out = [
            WorkflowSummaryResponse.from_workflow(w).model_dump() for w in _accessible(os.workflows, "workflows")
        ]

        # Surface components registered in the DB registry too, so anything created there is
        # discoverable -- and therefore runnable -- over MCP, matching the REST list routes.
        if os.db is not None and isinstance(os.db, BaseDb):
            from agno.agent.agent import get_agents
            from agno.team.team import get_teams
            from agno.workflow.workflow import get_workflows

            registry = os.registry
            # Owner scope for the DB-backed components, matching the REST list routes.
            scoped_user_id = _scoped_caller_user_id()
            # Exclude the ids this OS serves - what the code half above
            # renders - not the registry's, which is a superset carrying
            # rehydration context this listing never shows.
            agent_exclude = {aid for a in os.agents or [] if (aid := getattr(a, "id", None)) is not None} or None
            for a in _accessible(
                get_agents(db=os.db, registry=registry, exclude_component_ids=agent_exclude, user_id=scoped_user_id),
                "agents",
            ):
                try:
                    agents_out.append(AgentSummaryResponse.from_agent(a).model_dump())
                except Exception:
                    logger.exception("Error summarizing DB agent for get_agentos_config")
            team_exclude = {tid for t in os.teams or [] if (tid := getattr(t, "id", None)) is not None} or None
            for t in _accessible(
                get_teams(db=os.db, registry=registry, exclude_component_ids=team_exclude, user_id=scoped_user_id),
                "teams",
            ):
                try:
                    teams_out.append(TeamSummaryResponse.from_team(t).model_dump())
                except Exception:
                    logger.exception("Error summarizing DB team for get_agentos_config")
            workflow_exclude = {wid for w in os.workflows or [] if (wid := getattr(w, "id", None)) is not None} or None
            for w in _accessible(
                get_workflows(
                    db=os.db, registry=registry, exclude_component_ids=workflow_exclude, user_id=scoped_user_id
                ),
                "workflows",
            ):
                try:
                    workflows_out.append(WorkflowSummaryResponse.from_workflow(w, is_component=True).model_dump())
                except Exception:
                    logger.exception("Error summarizing DB workflow for get_agentos_config")

        return {
            "os_id": os.id or "AgentOS",
            "description": os.description,
            # A db shared by several components is registered once per component in os.dbs,
            # so collect the ids into a set to list each database once -- matching the REST /config route.
            "databases": list({db.id for db_id, dbs in os.dbs.items() for db in dbs}),
            "agents": agents_out,
            "teams": teams_out,
            "workflows": workflows_out,
        }

    # ==================== Core Run Tools ====================

    @register_builtin_tool(
        name="run_agent",
        title="Run Agent",
        description=(
            "Run an agent with a message and get its response. Pass a session_id from get_sessions to "
            "continue that conversation; omit it to start a new one (the session_id comes back in "
            "structuredContent). If the result status is PAUSED, resolve the returned requirements and "
            "call continue_run. Agent ids come from get_agentos_config."
        ),
        tags={"core"},
        annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True},
    )  # type: ignore
    async def run_agent(
        agent_id: str,
        message: str,
        ctx: Context,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> ToolResult:
        _require_tool_scopes("POST", f"/agents/{agent_id}/runs")
        user_id = _resolve_user_id(user_id)
        agent = await _resolve_run_component(os, "agents", agent_id, user_id=user_id, session_id=session_id)
        # Mint a fresh session per call when omitted (matches REST), never the sticky default.
        session_id = _session_id_or_new(session_id)
        await _assert_session_writable_mcp(os, agent, session_id, user_id, SessionType.AGENT)
        run_output = await _run_agentic_component(
            ctx, agent, message, user_id, session_id, label=f"Agent {agent.name or agent_id}"
        )
        return build_run_tool_result(run_output, result_mode)

    @register_builtin_tool(
        name="run_team",
        title="Run Team",
        description=(
            "Run a team of agents with a message and get its response. Same session and PAUSED semantics "
            "as run_agent. Team ids come from get_agentos_config."
        ),
        tags={"core"},
        annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True},
    )  # type: ignore
    async def run_team(
        team_id: str,
        message: str,
        ctx: Context,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> ToolResult:
        _require_tool_scopes("POST", f"/teams/{team_id}/runs")
        user_id = _resolve_user_id(user_id)
        team = await _resolve_run_component(os, "teams", team_id, user_id=user_id, session_id=session_id)
        # Mint a fresh session per call when omitted (matches REST), never the sticky default.
        session_id = _session_id_or_new(session_id)
        await _assert_session_writable_mcp(os, team, session_id, user_id, SessionType.TEAM)
        run_output = await _run_agentic_component(
            ctx, team, message, user_id, session_id, label=f"Team {team.name or team_id}"
        )
        return build_run_tool_result(run_output, result_mode)

    @register_builtin_tool(
        name="run_workflow",
        title="Run Workflow",
        description=(
            "Run a workflow with an input message and get its result. Can be long-running: progress is "
            "reported per step when the client supports it. Same session and PAUSED semantics as "
            "run_agent. Workflow ids come from get_agentos_config."
        ),
        tags={"core"},
        annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True},
    )  # type: ignore
    async def run_workflow(
        workflow_id: str,
        message: str,
        ctx: Context,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> ToolResult:
        from agno.workflow.remote import RemoteWorkflow

        _require_tool_scopes("POST", f"/workflows/{workflow_id}/runs")
        user_id = _resolve_user_id(user_id)
        workflow = await _resolve_run_component(os, "workflows", workflow_id, user_id=user_id, session_id=session_id)
        # Mint a fresh session per call when omitted (matches REST), never the sticky default.
        session_id = _session_id_or_new(session_id)
        await _assert_session_writable_mcp(os, workflow, session_id, user_id, SessionType.WORKFLOW)
        # Detach from FastMCP's tool-call span so the workflow run is its own root trace.
        with _detached_trace_context():
            if isinstance(workflow, RemoteWorkflow):
                run_output = await workflow.arun(
                    message, user_id=user_id, session_id=session_id, auth_token=_forwarded_auth_token()
                )
                return build_run_tool_result(run_output, result_mode)
            steps = getattr(workflow, "steps", None)
            total_steps = float(len(steps)) if isinstance(steps, (list, tuple)) and steps else None
            stream = workflow.arun(
                message,
                user_id=user_id,
                session_id=session_id,
                stream=True,
                stream_events=True,
            )
            run_output = await _consume_workflow_stream(ctx, workflow, stream, total_steps, user_id)
        return build_run_tool_result(run_output, result_mode)

    # ==================== Run Lifecycle Tools ====================

    @register_builtin_tool(
        name="continue_run",
        title="Continue Paused Run",
        description=(
            "Resume a PAUSED run after resolving its requirements (human-in-the-loop). "
            "When a run tool returns status=PAUSED, its structuredContent carries the unresolved "
            "requirements; set the resolution fields on them (e.g. confirmation=true) and pass them "
            "back here unchanged otherwise. Provide exactly one of agent_id / team_id / workflow_id "
            "(the component that owns the run) plus the run_id and session_id from the paused result."
        ),
        tags={"core", "lifecycle"},
        annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True},
    )  # type: ignore
    async def continue_run(
        run_id: str,
        ctx: Context,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        requirements: Optional[List[Dict[str, Any]]] = None,
        user_id: Optional[str] = None,
    ) -> ToolResult:
        component_type, component_id = _classify_lifecycle_target(agent_id, team_id, workflow_id)
        _require_published_component("continue_run", component_type, component_id)
        _require_tool_scopes("POST", f"/{component_type}/{component_id}/runs/{run_id}/continue")
        user_id = _resolve_user_id(user_id)
        # published_only=False, like the REST /continue routes: the run may live
        # on a draft-only preview component that has no published version.
        component = await _resolve_run_component(
            os, component_type, component_id, user_id=user_id, session_id=session_id, published_only=False
        )
        await _verify_run_ownership(component, component_type, component_id, session_id, run_id)
        # A run paused on an admin-required approval must be resolved by an admin, not
        # self-continued by its initiator; same gate the REST /continue route enforces.
        await _enforce_run_continuation_allowed(os.db, run_id)
        # Version-stable continuation: a run started with an explicitly pinned
        # version (draft preview) recorded it in its run metadata; continue on
        # THAT version, not whatever is published/current now - same rule as the
        # REST /continue routes. The resolver re-applies the draft-preview gate
        # for the stamped version, so a forged stamp cannot reach a draft this
        # caller may not preview. No stamp (legacy or unpinned runs) keeps
        # today's resolution. Factories build per-request and remote components
        # resolve remotely, so both are exempt; the stamp lives on the run,
        # which is only readable with its session.
        roster = {"agents": os.agents, "teams": os.teams, "workflows": os.workflows}[component_type]
        if session_id and not isinstance(component, BaseRemote) and find_factory_by_id(component_id, roster) is None:
            stamped_run = await component.aget_run_output(run_id=run_id, session_id=session_id, user_id=user_id)
            stamped_version = stamped_component_version(stamped_run)
            if stamped_version is not None:
                component = await _resolve_run_component(
                    os,
                    component_type,
                    component_id,
                    user_id=user_id,
                    session_id=session_id,
                    version=stamped_version,
                    published_only=False,
                )
        await _report_progress(ctx, 0.0, f"Continuing run {run_id}")
        try:
            # Detach from FastMCP's tool-call span so the resumed run is its own root trace.
            with _detached_trace_context():
                run_output = await run_service.continue_paused_run(
                    component,
                    run_id=run_id,
                    session_id=session_id,
                    user_id=user_id,
                    requirements=requirements,
                )
        except run_service.RemoteContinuationUnsupported as e:
            raise Exception(str(e))
        return build_run_tool_result(run_output, result_mode)

    @register_builtin_tool(
        name="cancel_run",
        title="Cancel Run",
        description=(
            "Request cancellation of a running run. Irreversible: the run stops and is marked CANCELLED "
            "(if it has not started yet, the intent is recorded and applied when it does). Provide the "
            "run_id, its session_id, and exactly one of agent_id / team_id / workflow_id."
        ),
        tags={"core", "lifecycle"},
        annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": True},
    )  # type: ignore
    async def cancel_run(
        run_id: str,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
    ) -> str:
        component_type, component_id = _classify_lifecycle_target(agent_id, team_id, workflow_id)
        _require_published_component("cancel_run", component_type, component_id)
        _require_tool_scopes("POST", f"/{component_type}/{component_id}/runs/{run_id}/cancel")
        # Factory components cancel STATICALLY (mirrors the REST factory-cancel routes):
        # cancellation is a run_id-keyed global intent, so building the factory is both
        # unnecessary and harmful -- generic resolution invokes it, which 400s a
        # required-input factory or a request-less transport and would make a live
        # factory run uncancellable over MCP.
        roster = {"agents": os.agents, "teams": os.teams, "workflows": os.workflows}[component_type]
        factory = find_factory_by_id(component_id, roster)
        if factory is not None:
            await _verify_factory_run_ownership(
                getattr(factory, "db", None) or os.db, component_type, component_id, session_id, run_id
            )
            await _static_cancel_factory_run(component_type, run_id)
            return f"Run {run_id} cancellation requested"
        # Lenient: cancel needs only a handle on the component, and a drifted
        # registry must never make a run uncancellable. Matches the REST route
        # (strict=False, published_only=False - a draft-only preview run must
        # stay cancellable even though its component has no published version).
        component = await _resolve_run_component(
            os, component_type, component_id, user_id=None, session_id=session_id, strict=False, published_only=False
        )
        await _verify_run_ownership(component, component_type, component_id, session_id, run_id)
        await run_service.cancel_component_run(component, run_id, auth_token=_forwarded_auth_token())
        return f"Run {run_id} cancellation requested"

    # ==================== Session Tools (read-only) ====================
    # The MCP session surface is deliberately read-only continuity: run tools create
    # sessions implicitly, and destructive session management stays on the REST surface.

    @register_builtin_tool(
        name="get_sessions",
        title="List Sessions",
        description=(
            "List past sessions (conversations), newest first. Filter by session_type, component_id "
            "(an agent/team/workflow id from get_agentos_config), user, or session_name. Use a returned "
            "session_id with the run tools to continue that conversation, or with get_session_runs to "
            "read its history. db_id is only needed when get_agentos_config lists multiple databases."
        ),
        tags={"session"},
        annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    )  # type: ignore
    async def get_sessions(
        session_type: Literal["agent", "team", "workflow"] = "agent",
        component_id: Optional[str] = None,
        user_id: Optional[str] = None,
        session_name: Optional[str] = None,
        limit: int = 20,
        page: int = 1,
        sort_by: str = "created_at",
        sort_order: Literal["asc", "desc"] = "desc",
        db_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        _require_tool_scopes("GET", "/sessions")
        user_id = _scoped_read_user_id(user_id)
        db = await get_db(os.dbs, db_id)
        session_type_enum = SessionType(session_type)

        if isinstance(db, RemoteDb):
            result = await db.get_sessions(
                session_type=session_type_enum,
                component_id=component_id,
                user_id=user_id,
                session_name=session_name,
                limit=limit,
                page=page,
                sort_by=sort_by,
                sort_order=sort_order,
                db_id=db_id,
                headers=_forwarded_auth_headers(),
            )
            return result.model_dump()

        sessions, total_count = await session_service.get_sessions_page(
            db,
            session_type=session_type_enum,
            component_id=component_id,
            user_id=user_id,
            session_name=session_name,
            limit=limit,
            page=page,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        total_pages = (total_count + limit - 1) // limit if limit > 0 else 0
        return PaginatedResponse(
            data=[SessionSchema.from_dict(session) for session in sessions],
            meta=PaginationInfo(page=page, limit=limit, total_count=total_count, total_pages=total_pages),
        ).model_dump()

    @register_builtin_tool(
        name="get_session_runs",
        title="Read Session History",
        description=(
            "Read a session's conversation history: each run's input and response content with its "
            "run_id, status, and timestamp, oldest first. Returns the answer content only, not the full "
            "message transcript. Pass run_id to get that one run in FULL, untrimmed detail -- the complete "
            "message transcript INCLUDING the system prompt/instructions, plus every event and metric. "
            "This is the debugging escape hatch and can be large (a long run returns a lot of tokens), so "
            "request a specific run_id deliberately, not by default. session_type is auto-detected when "
            "omitted; db_id is only needed when get_agentos_config lists multiple databases."
        ),
        tags={"session"},
        annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    )  # type: ignore
    async def get_session_runs(
        session_id: str,
        run_id: Optional[str] = None,
        session_type: Optional[Literal["agent", "team", "workflow"]] = None,
        user_id: Optional[str] = None,
        db_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        _require_tool_scopes("GET", f"/sessions/{session_id}/runs")
        user_id = _scoped_read_user_id(user_id)
        db = await get_db(os.dbs, db_id)
        session_type_enum = SessionType(session_type) if session_type else None

        if isinstance(db, RemoteDb):
            runs = await db.get_session_runs(
                session_id=session_id,
                session_type=session_type_enum,
                user_id=user_id,
                db_id=db_id,
                headers=_forwarded_auth_headers(),
            )
        else:
            # SessionNotFoundError propagates as the tool error verbatim ("Session {id} not found").
            runs = await session_service.get_session_runs(
                db, session_id=session_id, session_type=session_type_enum, user_id=user_id
            )

        if run_id is not None:
            for run in runs:
                data = run.model_dump() if hasattr(run, "model_dump") else dict(run)
                if data.get("run_id") == run_id:
                    return [data]
            raise Exception(f"Run {run_id} not found in session {session_id}")
        return [trim_session_run(r) for r in runs]

    # Register any user-provided custom tools. These share the same server, mount (/mcp),
    # lifespan, and JWT middleware as the built-in tools.
    custom_tool_names = _register_custom_tools(mcp, custom_entries, enabled_tags)

    # Expose the components named in the config as individual tools ("chief", not
    # run_agent(agent_id="chief")). Last, so collision checks see the full surface.
    _register_exposed_components(mcp, os, result_mode, custom_tool_names, exposure_entries, enabled_tags)

    return mcp


class _MCPAuthorizeMiddleware:
    """Gate the MCP server with a per-call ``authorize(user_id) -> bool`` predicate.

    Runs after the identity is attached to ``request.state`` (by the parent auth
    middleware, or by the identity bridge under ``mcp_auth``) and returns 401 before
    any tool or model runs when the predicate rejects the caller.

    ``only_path`` scopes the gate to the MCP endpoint itself: under ``mcp_auth`` the
    sub-app also serves the provider's OAuth flow endpoints (/authorize, /token,
    /register), which are unauthenticated by design and must not be gated.

    ``defer_unauthenticated`` (set under ``mcp_auth``) passes unauthenticated requests
    through so the SDK's RequireAuthMiddleware at the route answers them with the
    RFC 9728 challenge (401 + WWW-Authenticate) -- a plain 401 from this gate would
    break connector discovery. The gate then adjudicates only verified callers.
    """

    def __init__(
        self,
        app: Any,
        authorize: Callable[[Optional[str]], bool],
        only_path: Optional[str] = None,
        defer_unauthenticated: bool = False,
    ) -> None:
        self.app = app
        self.authorize = authorize
        self.only_path = only_path
        self.defer_unauthenticated = defer_unauthenticated

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http" and (self.only_path is None or scope.get("path") == self.only_path):
            state = scope.get("state") or {}
            if self.defer_unauthenticated and not state.get("authenticated"):
                await self.app(scope, receive, send)
                return
            user_id = state.get("user_id")
            if not self.authorize(user_id):
                from starlette.responses import JSONResponse

                response = JSONResponse(
                    {"error": "unauthorized", "detail": "Not authorized for the MCP server."},
                    status_code=401,
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def _add_authorize_middleware(mcp_app: StarletteWithLifespan, authorize: Callable[[Optional[str]], bool]) -> None:
    mcp_app.add_middleware(_MCPAuthorizeMiddleware, authorize=authorize)


def _identity_bridge_kwargs(os: "AgentOS") -> Dict[str, Any]:
    """The identity bridge's settings, mirroring the parent AuthMiddleware.

    Same admin scope (per-tool admin bypass) and user-isolation flag (session pinning
    via get_scoped_user_id) as the parent would stamp, so behavior is identical whether
    the identity came from the parent middleware or from ``mcp_auth``.
    """
    from agno.os.scopes import AgentOSScope

    config = getattr(os, "authorization_config", None)
    admin_scope = getattr(config, "admin_scope", None) if config is not None else None
    user_isolation = bool(getattr(config, "user_isolation", False)) if config is not None else False
    return {"admin_scope": admin_scope or AgentOSScope.ADMIN.value, "user_isolation": user_isolation}


# Localhost defaults so a desktop / local MCP server is protected with zero extra config.
_MCP_LOCALHOST_HOSTS = ("127.0.0.1", "localhost", "[::1]")


def _mcp_request_hostname(host_header: str) -> str:
    """Bare hostname from a Host header value, port stripped (keeps the ipv6 brackets)."""
    value = host_header.strip()
    if value.startswith("["):  # ipv6 literal, e.g. [::1]:7777
        end = value.find("]")
        return value[: end + 1] if end != -1 else value
    return value.split(":", 1)[0]


def _mcp_origin_hostname(origin: str) -> str:
    """Bare hostname from an Origin header value (keeps ipv6 brackets to match the defaults)."""
    from urllib.parse import urlparse

    hostname = urlparse(origin).hostname or ""
    return f"[{hostname}]" if ":" in hostname else hostname


def _mcp_host_allowed(hostname: str, allowed: set) -> bool:
    if hostname in allowed:
        return True
    return any(pattern.startswith("*.") and hostname.endswith(pattern[1:]) for pattern in allowed)


def _add_transport_security_middleware(
    mcp_app: StarletteWithLifespan,
    allowed_hosts: List[str],
    allowed_origins: Optional[List[str]],
) -> None:
    """Add built-in DNS-rebinding protection: validate the Host (and Origin when present).

    Allowed hosts always include localhost, so a desktop / local MCP server works out of the box;
    callers list only their deploy or tunnel host. Anything else is rejected with 400 before the
    request reaches the MCP machinery.
    """
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    host_set = {_mcp_request_hostname(h) for h in list(allowed_hosts) + list(_MCP_LOCALHOST_HOSTS)}
    origin_set = set(allowed_origins or [])

    class _MCPTransportSecurityMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):  # type: ignore[no-untyped-def]
            host = _mcp_request_hostname(request.headers.get("host", ""))
            if not _mcp_host_allowed(host, host_set):
                return JSONResponse({"error": "invalid_host", "detail": "Host not allowed."}, status_code=400)
            origin = request.headers.get("origin")
            if (
                origin is not None
                and origin not in origin_set
                and not _mcp_host_allowed(_mcp_origin_hostname(origin), host_set)
            ):
                return JSONResponse({"error": "invalid_origin", "detail": "Origin not allowed."}, status_code=400)
            return await call_next(request)

    mcp_app.add_middleware(_MCPTransportSecurityMiddleware)


def _mcp_server_is_open(os: "AgentOS") -> bool:
    """True when /mcp serves anonymous callers: no auth is effectively enforced.

    ``mcp_auth`` protects /mcp on its own (its RequireAuthMiddleware challenges every
    unauthenticated request), so a deployment with it set is never open regardless of the
    REST posture -- checked here directly rather than via ``get_effective_auth_mode``,
    which now reports the REST/WS plane only. Otherwise this defers to that shared
    detection: ``AgentOS(authorization=True)``, JWT env vars, a manually installed
    ``JWTMiddleware`` on a ``base_app``, and the security key all count as authenticated.
    Only the fully-anonymous case (no mcp_auth and REST mode "none") answers requests
    carrying no bearer token -- the case a rebound web page could drive, so the one that
    needs default transport security. A service-account verifier alone does NOT close that
    path (PATs are checked only when presented).
    """
    from agno.os.auth import get_effective_auth_mode

    if getattr(os, "mcp_auth", None) is not None:
        return False
    return (
        get_effective_auth_mode(
            getattr(os, "settings", None),
            bool(getattr(os, "authorization", False)),
            getattr(os, "base_app", None),
        )
        == "none"
    )


def get_mcp_server(
    os: "AgentOS",
) -> StarletteWithLifespan:
    """Build the MCP HTTP app served at ``/mcp``.

    Wraps :func:`build_mcp_server` with the Streamable HTTP transport and layers on
    the optional ``authorize`` gate, any app-provided middleware, and the built-in
    DNS-rebinding protection from ``mcp_config``.

    Authentication: with ``mcp_auth`` unset, it is NOT layered here -- the parent app's
    single ``AuthMiddleware`` (agno/os/app.py::_add_auth_middleware) runs before
    Starlette dispatches to this mount, so it already verified the token and attached
    the identity to request.state. With ``mcp_auth`` set, the fastmcp provider owns
    authentication for this app instead: its middleware verifies tokens here, the
    identity bridge maps them onto request.state, and the parent middleware exempts
    the MCP surface. Per-tool scope enforcement lives in the tools themselves
    (``_require_tool_scopes``).
    """
    mcp = build_mcp_server(os)
    mcp_config: "Optional[MCPConfig]" = getattr(os, "mcp_config", None)
    mcp_auth = os._get_mcp_auth_provider()

    # Use http_app for Streamable HTTP transport (modern MCP standard).
    # fastmcp >= 3.4.3 adds a Host/Origin guard with localhost-only defaults, which 421s
    # deployed hosts before our own middleware runs. Disable it where the parameter exists
    # and run AgentOS's single validation engine instead (the transport-security middleware
    # below), which protects open servers by default and lets deployed hosts opt in via
    # MCPConfig.allowed_hosts.
    http_app_kwargs: Dict[str, Any] = {"path": "/mcp"}
    if "host_origin_protection" in inspect.signature(mcp.http_app).parameters:
        http_app_kwargs["host_origin_protection"] = False
    if mcp_auth is not None:
        # Constructor middleware runs INSIDE fastmcp's authentication middleware (the
        # app's middleware list is auth first, then these) -- the only placement where
        # the bridge sees the verified token and the authorize gate sees the bridged
        # user_id. add_middleware would prepend OUTSIDE authentication instead.
        from starlette.middleware import Middleware as StarletteMiddleware

        from agno.os.mcp_auth import MCPIdentityBridgeMiddleware

        inner_middleware: List[Any] = [StarletteMiddleware(MCPIdentityBridgeMiddleware, **_identity_bridge_kwargs(os))]
        if mcp_config is not None and mcp_config.authorize is not None:
            inner_middleware.append(
                StarletteMiddleware(
                    _MCPAuthorizeMiddleware,
                    authorize=mcp_config.authorize,
                    only_path="/mcp",
                    defer_unauthenticated=True,
                )
            )
        http_app_kwargs["middleware"] = inner_middleware
    mcp_app = mcp.http_app(**http_app_kwargs)
    if mcp_auth is not None:
        # Arms the fail-closed check in the tool gates (_mcp_auth_enabled): a
        # provider-verified request with no bridged identity is denied, not skipped.
        mcp_app.state.agno_mcp_auth_enabled = True

    # Middleware runs in reverse registration order (last added is outermost / runs first).
    # Target running order: transport security -> app middleware -> authorize gate -> tool.
    # Auth already ran on the parent app, so the gate sees the verified identity.

    # Innermost: per-call authorize gate. Under mcp_auth it is registered inside the
    # sub-app's constructor middleware above (after token verification) instead.
    if mcp_auth is None and mcp_config is not None and mcp_config.authorize is not None:
        # The gate reads request.state.user_id, populated by the parent AuthMiddleware.
        # Without any auth configured that attribute is never set, so the gate sees
        # user_id=None on every call -- an ``authorize=lambda u: u in OWNER_IDS`` gate
        # then rejects everyone (or "allows" everyone if permissive on None). Warn loudly.
        if not os.authorization:
            from agno.utils.log import log_warning

            log_warning(
                "MCPConfig.authorize is set but AgentOS(authorization=False); the gate will "
                "be called with user_id=None on every request because no JWT middleware populates "
                "request.state.user_id. Either pass authorization=True with an authorization_config, "
                "or write your authorize() to handle user_id=None explicitly (e.g. for a dev shortcut)."
            )
        _add_authorize_middleware(mcp_app, mcp_config.authorize)

    # App-provided middleware, preserving the order they were listed in.
    if mcp_config is not None and mcp_config.middleware:
        for mw in reversed(mcp_config.middleware):
            cls, args, kwargs = mw
            mcp_app.add_middleware(cls, *args, **kwargs)

    # Outermost: built-in DNS-rebinding protection (runs first, before auth and tools).
    #
    # A configured ``allowed_hosts`` always applies. On top of that, when the server is OPEN
    # (no JWT and no security key, so /mcp answers anonymous callers) we default to
    # localhost-only protection even without ``allowed_hosts`` -- this is the one config a
    # rebound web page could drive, and it restores the safe default fastmcp's own guard gave
    # before we disabled it. Authenticated deployments rely on the bearer token, which a
    # rebinding attacker cannot supply, so protection there stays opt-in: their real hostname
    # is not gated (the 421/400 regression the built-in guard caused) unless they set
    # ``allowed_hosts`` themselves.
    allowed_hosts = mcp_config.allowed_hosts if mcp_config is not None else None
    allowed_origins = mcp_config.allowed_origins if mcp_config is not None else None
    if allowed_hosts is None and _mcp_server_is_open(os):
        allowed_hosts = []
    if allowed_hosts is not None:
        _add_transport_security_middleware(mcp_app, allowed_hosts, allowed_origins)

    return mcp_app
