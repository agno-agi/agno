"""Unit tests for toolkits served as MCP tools, and the parameters the server fills.

Two behaviours that only make sense together. A ``Toolkit`` passed to ``MCPConfig.tools``
is flattened into one MCP tool per method, the way an agent takes it apart -- and real
toolkit methods declare ``run_context: RunContext``, which pydantic cannot describe, so
flattening without hiding the framework's own parameters would fail at startup rather
than publish anything.

The FastMCP tool surface is exercised with an in-memory client, matching
test_mcp_exposed_components.py.
"""

import pytest

pytest.importorskip("fastmcp")

import tempfile  # noqa: E402
from typing import List, Optional, Union  # noqa: E402

from fastmcp import Client, Context  # noqa: E402

import agno.os.mcp as mcp_mod  # noqa: E402
from agno.agent import Agent  # noqa: E402
from agno.db.sqlite import SqliteDb  # noqa: E402
from agno.media import Image  # noqa: E402
from agno.os import AgentOS, MCPConfig  # noqa: E402
from agno.os.mcp import build_mcp_server  # noqa: E402
from agno.run import RunContext  # noqa: E402
from agno.team.team import Team  # noqa: E402
from agno.tools import Toolkit, tool  # noqa: E402
from agno.tools.function import Function  # noqa: E402


def _agent(id: str = "demo-agent") -> Agent:
    return Agent(id=id, name="Demo Agent")


def _os(*tools, default_tools: bool = False) -> AgentOS:
    return AgentOS(agents=[_agent()], mcp=MCPConfig(tools=list(tools), default_tools=default_tools))


async def _tools_by_name(os: AgentOS) -> dict:
    async with Client(build_mcp_server(os)) as client:
        return {t.name: t for t in await client.list_tools()}


async def _props(os: AgentOS, name: str) -> dict:
    return ((await _tools_by_name(os))[name].inputSchema or {}).get("properties", {})


async def _props_of_only_tool(*tools) -> dict:
    """Schema properties of a single-tool server, keyed off whatever name it took."""
    registry = await _tools_by_name(_os(*tools))
    assert len(registry) == 1, registry
    return (next(iter(registry.values())).inputSchema or {}).get("properties", {})


class Notebook(Toolkit):
    """A toolkit shaped like the real ones: identity first, then the model's arguments."""

    def __init__(self, **kwargs):
        super().__init__(name="notebook", tools=[self.jot, self.recall], **kwargs)

    def jot(self, run_context: RunContext, note: str, tag: Optional[str] = None) -> str:
        """Write a note down."""
        return f"user={run_context.user_id} note={note} tag={tag}"

    async def recall(self, run_context: RunContext) -> str:
        """Read the notes back."""
        return f"user={run_context.user_id}"


class Shadow(Toolkit):
    """A toolkit whose method names a default MCP tool."""

    def __init__(self, **kwargs):
        super().__init__(name="shadow", tools=[self.run_agent], **kwargs)

    def run_agent(self, q: str) -> str:
        """Shadows the built-in run_agent."""
        return q


class Dangerous(Toolkit):
    """A toolkit carrying an approval gate the MCP surface cannot honour."""

    def __init__(self, **kwargs):
        super().__init__(name="dangerous", tools=[self.wipe], requires_confirmation_tools=["wipe"], **kwargs)

    def wipe(self, path: str) -> str:
        """Delete everything under a path."""
        return path


# ==================== Flattening a toolkit ====================


async def test_toolkit_is_flattened_into_one_tool_per_method():
    """A Toolkit publishes its methods individually, and nothing else."""
    registry = await _tools_by_name(_os(Notebook()))

    assert set(registry) == {"jot", "recall"}
    assert registry["jot"].description == "Write a note down."


async def test_flattened_tools_hide_the_framework_parameter_and_keep_the_rest():
    """``run_context`` never reaches the client; the model-facing arguments all do."""
    assert sorted(await _props(_os(Notebook()), "jot")) == ["note", "tag"]
    assert await _props(_os(Notebook()), "recall") == {}


async def test_flattened_tool_receives_the_authenticated_caller(monkeypatch):
    """The hidden RunContext is really built and really carries the JWT subject.

    The schema assertions above would pass just as well if the server hid the parameter
    and then never filled it, so this one calls the tool.
    """
    monkeypatch.setattr(mcp_mod, "_resolve_user_id", lambda caller: "jwt-subject-42")

    async with Client(build_mcp_server(_os(Notebook()))) as client:
        result = await client.call_tool("jot", {"note": "hello"})

    assert result.content[0].text == "user=jwt-subject-42 note=hello tag=None"


async def test_self_is_not_published_as_a_tool_argument():
    """The entrypoint is a bound method, so ``self`` must never reach the schema."""
    for name in ("jot", "recall"):
        assert "self" not in await _props(_os(Notebook()), name)


async def test_toolkit_include_and_exclude_filters_are_respected():
    """Flattening reads the toolkit's own surface, so its filters already applied."""
    assert set(await _tools_by_name(_os(Notebook(exclude_tools=["recall"])))) == {"jot"}
    assert set(await _tools_by_name(_os(Notebook(include_tools=["recall"])))) == {"recall"}


async def test_async_variant_wins_when_a_toolkit_declares_both():
    """One name, one tool: the async surface is what an async caller would run."""

    class Both(Toolkit):
        def __init__(self):
            super().__init__(name="both", tools=[self.ping, self.aping])

        def ping(self, q: str) -> str:
            """Sync."""
            return f"sync:{q}"

        @tool(name="ping")
        async def aping(self, q: str) -> str:
            """Async."""
            return f"async:{q}"

    kit = Both()
    registry = await _tools_by_name(_os(kit))
    assert set(registry) == {"ping"}
    async with Client(build_mcp_server(_os(kit))) as client:
        assert (await client.call_tool("ping", {"q": "x"})).content[0].text == "async:x"


async def test_toolkit_mixes_with_components_and_plain_callables():
    """A toolkit entry is classified as a custom tool, not mistaken for a component."""

    async def standalone(q: str) -> str:
        """A plain callable."""
        return q

    agent = _agent("chief")
    os = AgentOS(
        agents=[agent],
        mcp=MCPConfig(tools=[Notebook(), agent, standalone], default_tools=False, lifecycle_tools=False),
    )
    assert set(await _tools_by_name(os)) == {"jot", "recall", "chief", "standalone"}


async def test_toolkit_subclass_with_arun_is_still_a_custom_tool():
    """A Toolkit carries an id like a component does; type decides, not the heuristics."""

    class Runner(Toolkit):
        def __init__(self):
            super().__init__(name="runner", tools=[self.ping])

        async def arun(self, *args, **kwargs):  # noqa: D102
            raise AssertionError("never called")

        def ping(self, q: str) -> str:
            """Ping."""
            return q

    assert set(await _tools_by_name(_os(Runner()))) == {"ping"}


async def test_toolkit_publishing_nothing_is_refused():
    """A toolkit filtered down to nothing would publish nothing; say so at startup."""
    with pytest.raises(ValueError, match="registers no functions"):
        build_mcp_server(_os(Notebook(exclude_tools=["jot", "recall"])))


async def test_flattened_toolkit_publishes_its_presentation_metadata():
    """title/annotations declared on a toolkit method survive the flatten."""

    class Titled(Toolkit):
        def __init__(self):
            super().__init__(name="titled", tools=[self.lookup])

        @tool(title="Weather Lookup", annotations={"readOnlyHint": True})
        def lookup(self, city: str) -> str:
            """Look up the weather."""
            return city

    published = (await _tools_by_name(_os(Titled())))["lookup"]
    assert published.title == "Weather Lookup"
    assert published.annotations.readOnlyHint is True


# ==================== Collisions on a flattened name ====================


async def test_flattened_name_colliding_with_a_default_tool_is_refused():
    """A toolkit method named like a built-in must not silently replace it."""
    with pytest.raises(ValueError) as excinfo:
        build_mcp_server(_os(Shadow(), default_tools=True))

    message = str(excinfo.value)
    assert 'collides with the default tool "run_agent"' in message
    # The deployer cannot rename someone else's method, so the advice names the knob
    # that actually frees the name.
    assert 'exclude_tools=["run_agent"]' in message
    assert 'toolkit "shadow"' in message


async def test_two_toolkits_sharing_a_method_name_are_refused():
    """FastMCP would replace the first tool; the collision check raises instead."""
    with pytest.raises(ValueError) as excinfo:
        build_mcp_server(_os(Notebook(include_tools=["jot"]), Notebook(include_tools=["jot"])))

    message = str(excinfo.value)
    assert 'collides with toolkit "notebook" tool "jot"' in message
    assert 'exclude_tools=["jot"]' in message


async def test_a_flattened_name_blocks_a_later_exposed_component():
    """Flattened names join the registry the exposure check reads."""
    agent = Agent(id="jot", name="Jot")
    os = AgentOS(agents=[agent], mcp=MCPConfig(tools=[Notebook(), agent], default_tools=False))

    with pytest.raises(ValueError, match='toolkit "notebook" tool "jot"'):
        build_mcp_server(os)


# ==================== Approval gates the MCP surface cannot honour ====================


async def test_gated_toolkit_method_is_refused_rather_than_published_ungated():
    """An MCP call runs the entrypoint directly, so a confirmation would be skipped."""
    with pytest.raises(ValueError) as excinfo:
        build_mcp_server(_os(Dangerous()))

    message = str(excinfo.value)
    assert "requires_confirmation" in message
    assert 'exclude_tools=["wipe"]' in message


async def test_real_toolkit_with_write_methods_is_refused():
    """The shipped Workspace toolkit gates its writes; flattening must not drop that."""
    from agno.tools.workspace import Workspace

    with tempfile.TemporaryDirectory() as tmp_dir:
        with pytest.raises(ValueError, match="requires_confirmation"):
            build_mcp_server(_os(Workspace(root=tmp_dir)))

        # Scoped down to the read-only surface it publishes cleanly.
        registry = await _tools_by_name(_os(Workspace(root=tmp_dir, allowed=["read", "list"])))
        assert set(registry) == {"read_file", "list_files"}


async def test_a_real_toolkit_flattens_with_its_run_context_hidden():
    """End to end on a shipped toolkit, which is where the two features meet."""
    from agno.tools.memory import MemoryTools

    kit = MemoryTools(db=SqliteDb(db_file=tempfile.mktemp(suffix=".db")), enable_think=False, enable_analyze=False)
    registry = await _tools_by_name(_os(kit))

    assert set(registry) == {"get_memories", "add_memory", "update_memory", "delete_memory"}
    assert (registry["add_memory"].inputSchema or {}).get("properties", {}).keys() == {"memory", "topics"}
    assert (registry["get_memories"].inputSchema or {}).get("properties", {}) == {}


# ==================== Hiding by type ====================


async def test_run_context_is_hidden_whatever_the_parameter_is_called():
    """The rule is the annotation, not the name -- authors name this one anything."""

    async def lookup(q: str, ctx: RunContext) -> str:
        """Look something up."""
        return q

    assert sorted(await _props_of_only_tool(lookup)) == ["q"]


async def test_agent_and_team_typed_parameters_are_hidden():
    """Framework objects an MCP caller has no business choosing."""

    async def get_info(query: str, helper: Agent, crew: Optional[Team] = None) -> str:
        """Get info."""
        return query

    assert sorted(await _props_of_only_tool(get_info)) == ["query"]


async def test_a_union_naming_an_identity_type_is_hidden_even_though_a_model_could_fill_it():
    """The MCP rule is broader than the model-facing one, and has to be.

    ``is_framework_typed`` keeps ``Union[str, Agent]`` in the model's schema, because the
    model can only ever send the string half. Pydantic builds THIS schema from the real
    signature and fails on Agent's own fields, so the server would not start.
    """

    async def lookup(query: str, owner: Union[str, Agent] = None) -> str:
        """Look up by owner."""
        return query

    assert sorted(await _props_of_only_tool(lookup)) == ["query"]


async def test_media_parameters_stay_visible():
    """Nothing on this surface injects media, so hiding it would leave it unfillable."""

    async def caption(pic: Image, gallery: Optional[List[Image]] = None) -> str:
        """Caption an image."""
        return "ok"

    assert sorted(await _props_of_only_tool(caption)) == ["gallery", "pic"]


async def test_a_sync_custom_tool_gets_the_same_hiding(monkeypatch):
    """The wrapper has two branches; the sync one is a real path for toolkit methods."""
    monkeypatch.setattr(mcp_mod, "_resolve_user_id", lambda caller: "sync-caller")

    def probe(note: str, ctx: RunContext) -> str:
        """A synchronous custom tool."""
        return f"{ctx.user_id}:{note}"

    os = _os(probe)
    assert sorted(await _props(os, "probe")) == ["note"]
    async with Client(build_mcp_server(os)) as client:
        assert (await client.call_tool("probe", {"note": "hi"})).content[0].text == "sync-caller:hi"


async def test_fastmcp_context_is_left_for_fastmcp_to_inject():
    """``Context`` is not an agno identity type and must keep its native injection."""

    async def whoami(ctx: Context) -> str:
        """Report the FastMCP context type."""
        return f"ctx:{type(ctx).__name__}"

    os = _os(whoami)
    assert await _props(os, "whoami") == {}
    async with Client(build_mcp_server(os)) as client:
        assert (await client.call_tool("whoami", {})).content[0].text == "ctx:Context"


# ==================== Hiding by name, and the split between the two paths ====================


async def test_a_plain_callable_keeps_parameters_merely_named_like_framework_ones():
    """A bare callable was written for this surface, so its own ``agent: str`` is its own.

    Hiding by name here would leave the parameter fillable by nobody: MCP has no agent,
    team or run media to put in it.
    """

    async def book(team: str, agent: str, images: str, files: str) -> str:
        """Book something."""
        return team

    assert sorted(await _props_of_only_tool(book)) == ["agent", "files", "images", "team"]


async def test_an_agno_function_hides_the_identity_names_it_already_hides_from_a_model():
    """The same object an agent would run must not have two contracts.

    ``_derive_entrypoint_schema`` keeps these names out of the model-facing schema and
    ``_build_entrypoint_args`` fills them, whether or not they are annotated. An
    unannotated ``run_context`` published over MCP would be a caller-supplied dict where
    the body expects the caller's identity.
    """

    @tool(name="probe")
    async def probe(note: str, run_context, agent, team) -> str:  # noqa: ANN001
        """A tool written for an agent."""
        return note

    assert sorted(await _props_of_only_tool(probe)) == ["note"]


async def test_media_names_are_hidden_on_neither_path():
    """Media is injected by reserved name on the agent path; there is no such source here."""

    @tool(name="attach")
    async def attach(note: str, images: Optional[List[str]] = None) -> str:
        """Attach something."""
        return note

    assert sorted(await _props_of_only_tool(attach)) == ["images", "note"]


# ==================== user_id, unchanged ====================


async def test_user_id_is_still_resolved_from_the_authenticated_request(monkeypatch):
    """The JWT subject is the server's to resolve, over any default the author wrote."""
    monkeypatch.setattr(mcp_mod, "_resolve_user_id", lambda caller: "jwt-subject")

    async def whoami(user_id: str = "service-account") -> str:
        """Report the caller."""
        return f"user={user_id}"

    os = _os(whoami)
    assert await _props(os, "whoami") == {}
    async with Client(build_mcp_server(os)) as client:
        assert (await client.call_tool("whoami", {})).content[0].text == "user=jwt-subject"


async def test_the_jwt_subject_overrides_an_author_default_even_when_it_resolves_to_none(monkeypatch):
    """``always`` is the rule that identity is not the author's to default away.

    Without it an unauthenticated call would run the tool as "service-account" -- a name
    the author picked, standing in for a caller the server could not identify.
    """
    monkeypatch.setattr(mcp_mod, "_resolve_user_id", lambda caller: None)

    async def whoami(user_id: str = "service-account") -> str:
        """Report the caller."""
        return f"user={user_id}"

    async with Client(build_mcp_server(_os(whoami))) as client:
        assert (await client.call_tool("whoami", {})).content[0].text == "user=None"


async def test_an_agno_function_agent_argument_is_bound_to_none_not_left_at_its_default():
    """An MCP call runs outside any component, so the framework names are bound, not skipped."""

    @tool(name="probe")
    async def probe(note: str, agent="author-default") -> str:  # noqa: ANN001
        """A tool written for an agent."""
        return f"{note}:{agent}"

    os = _os(probe)
    assert sorted(await _props(os, "probe")) == ["note"]
    async with Client(build_mcp_server(os)) as client:
        assert (await client.call_tool("probe", {"note": "hi"})).content[0].text == "hi:None"


async def test_a_required_agent_typed_parameter_is_bound_to_none():
    """An MCP call runs outside any component, so an Agent-typed argument arrives empty.

    This is the TYPE rule rather than the name rule: the parameter is required, so the
    binder's value is written rather than left to a default.
    """

    async def probe(note: str, helper: Agent) -> str:
        """A tool wanting an agent."""
        return f"{note}:{helper}"

    os = _os(probe)
    assert sorted(await _props(os, "probe")) == ["note"]
    async with Client(build_mcp_server(os)) as client:
        assert (await client.call_tool("probe", {"note": "hi"})).content[0].text == "hi:None"


async def test_a_sync_tool_also_sheds_a_hidden_parameters_annotation(monkeypatch):
    """The wrapper has two branches, and both hand FastMCP their own annotations."""
    monkeypatch.setattr(mcp_mod, "_resolve_user_id", lambda caller: "sync-subject")

    def probe(q: str, run_context=None) -> str:  # noqa: ANN001
        """A synchronous tool whose identity annotation is unresolvable."""
        return f"{q}/{getattr(run_context, 'user_id', run_context)}"

    probe.__annotations__ = {"q": str, "run_context": "RunContextOnlyForTypeCheckers", "return": str}
    unresolvable = Function(name="probe", entrypoint=probe, description="Probe.")

    os = _os(unresolvable)
    assert sorted(await _props(os, "probe")) == ["q"]
    async with Client(build_mcp_server(os)) as client:
        assert (await client.call_tool("probe", {"q": "x"})).content[0].text == "x/sync-subject"


async def test_a_toolkit_method_keeps_a_user_id_of_its_own():
    """``user_id`` on a toolkit method is a domain argument, not the caller's identity.

    Toolkit methods read identity from their RunContext; agno never injects ``user_id``
    by name. ZoomTools asks which Zoom account to read, defaulting to "me" -- filling
    that with the JWT subject would break the call rather than secure it.
    """

    class Meetings(Toolkit):
        def __init__(self):
            super().__init__(name="meetings", tools=[self.list_meetings])

        def list_meetings(self, user_id: str = "me") -> str:
            """List meetings for an account."""
            return user_id

    os = _os(Meetings())
    assert sorted(await _props(os, "list_meetings")) == ["user_id"]
    async with Client(build_mcp_server(os)) as client:
        assert (await client.call_tool("list_meetings", {})).content[0].text == "me"
        assert (await client.call_tool("list_meetings", {"user_id": "someone"})).content[0].text == "someone"


async def test_a_hidden_parameters_annotation_does_not_follow_the_wrapper_to_fastmcp(monkeypatch):
    """FastMCP reads annotations as well as the signature, so the leftovers must go.

    ``functools.wraps`` copies the wrapped function's whole ``__annotations__``. An
    annotation that cannot be resolved at all -- a framework type imported only under
    ``if TYPE_CHECKING`` -- then fails FastMCP's type adapter and the server never
    starts, even though the parameter was correctly hidden.
    """
    monkeypatch.setattr(mcp_mod, "_resolve_user_id", lambda caller: "jwt-subject")

    async def probe(q: str, run_context=None) -> str:  # noqa: ANN001
        """A tool whose identity annotation only exists for type checkers."""
        return f"{q}/{getattr(run_context, 'user_id', run_context)}"

    probe.__annotations__ = {"q": str, "run_context": "RunContextOnlyForTypeCheckers", "return": str}
    unresolvable = Function(name="probe", entrypoint=probe, description="Probe.")

    os = _os(unresolvable)
    assert sorted(await _props(os, "probe")) == ["q"]
    async with Client(build_mcp_server(os)) as client:
        assert (await client.call_tool("probe", {"q": "x"})).content[0].text == "x/jwt-subject"


async def test_a_tool_with_nothing_to_hide_is_registered_unchanged():
    """The wrapper short-circuits, so an ordinary tool reaches FastMCP as it always did."""

    async def echo(message: str) -> str:
        """Echo a message."""
        return message

    os = _os(echo)
    assert sorted(await _props(os, "echo")) == ["message"]
    async with Client(build_mcp_server(os)) as client:
        assert (await client.call_tool("echo", {"message": "hi"})).content[0].text == "hi"


# ==================== Signatures the server cannot fill ====================


async def test_a_positional_only_framework_parameter_is_refused_by_name():
    """Refused with the parameter's name, not a pydantic error naming FilterExpr.

    Every toolkit method puts its RunContext first, so leaving the un-injectable kinds
    visible is not a hypothetical: the server would fail to start on a type the tool
    author never wrote.
    """

    async def posonly(run_context: RunContext, /, q: str) -> str:
        """Positional-only identity."""
        return q

    with pytest.raises(ValueError) as excinfo:
        build_mcp_server(_os(posonly))

    message = str(excinfo.value)
    assert "positional-only" in message
    assert '"run_context"' in message


async def test_a_positional_only_user_id_is_refused_by_name():
    """The same rule covers the name-based half, which had the same latent break."""

    async def probe(user_id, /, q: str) -> str:  # noqa: ANN001
        """Positional-only user_id."""
        return q

    with pytest.raises(ValueError, match="positional-only"):
        build_mcp_server(_os(probe))


async def test_a_required_identity_parameter_nothing_can_fill_is_refused():
    """Hiding and filling are separate questions; a list of run contexts is neither."""

    async def batch(rows: List[RunContext]) -> str:
        """Take a batch of contexts."""
        return "ok"

    with pytest.raises(ValueError) as excinfo:
        build_mcp_server(_os(batch))

    message = str(excinfo.value)
    assert "nothing to fill it with" in message
    assert '"rows"' in message


async def test_an_optional_identity_parameter_nothing_can_fill_keeps_its_default():
    """Hidden, unfilled, and left to its own default rather than forced to None.

    The default is deliberately not None: with None the assertion could not tell the two
    apart, and "forced to None" is exactly the behaviour being ruled out.
    """

    async def batch(note: str, rows: Optional[List[RunContext]] = "author-default") -> str:  # type: ignore[assignment]
        """Take an optional batch."""
        return f"{note}:{rows}"

    os = _os(batch)
    assert sorted(await _props(os, "batch")) == ["note"]
    async with Client(build_mcp_server(os)) as client:
        assert (await client.call_tool("batch", {"note": "hi"})).content[0].text == "hi:author-default"


async def test_the_wrapper_binds_positional_arguments_around_a_hidden_first_parameter(monkeypatch):
    """Calling the registered callable positionally must not collide with the injection.

    FastMCP calls by keyword, so this is latent there -- but the wrapper advertises a
    signature that accepts positionals, and every RunContext-taking toolkit method puts
    the hidden parameter first.
    """
    monkeypatch.setattr(mcp_mod, "_resolve_user_id", lambda caller: "positional-caller")

    def probe(run_context: RunContext, note: str) -> str:
        """Identity first, like every real toolkit method."""
        return f"{run_context.user_id}:{note}"

    hidden = mcp_mod._mcp_hidden_params(probe, owner="probe", reserved_names=True)
    wrapped = mcp_mod._build_mcp_wrapper(probe, hidden)

    assert wrapped("hi") == "positional-caller:hi"
    assert wrapped(note="hi") == "positional-caller:hi"


async def test_an_unreadable_annotation_does_not_expose_its_neighbours(monkeypatch):
    """One parameter this walk cannot classify must not leave the next one published."""
    real = mcp_mod.annotation_reaches

    def raising(hint, targets):
        if hint is str:
            raise RuntimeError("cannot read this one")
        return real(hint, targets)

    monkeypatch.setattr(mcp_mod, "annotation_reaches", raising)

    async def probe(note: str = "", ctx: Optional[RunContext] = None) -> str:
        """A tool with one unclassifiable neighbour."""
        return note

    # `note` fails closed and is hidden; `ctx` keeps its own protection rather than
    # having it undone by an unrelated neighbour the walk could not read.
    hidden = mcp_mod._mcp_hidden_params(probe, owner="probe")
    assert sorted(hidden) == ["ctx", "note"]
    assert await _props_of_only_tool(probe) == {}


async def test_an_unclassifiable_required_parameter_is_refused_rather_than_published(monkeypatch):
    """Failing closed on a required parameter means refusing, not shipping it unfillable.

    The agent-facing path hides such a parameter and then raises on every call. Here the
    same fail-closed reading is surfaced at startup, naming the parameter.
    """
    real = mcp_mod.annotation_reaches

    def raising(hint, targets):
        if hint is str:
            raise RuntimeError("cannot read this one")
        return real(hint, targets)

    monkeypatch.setattr(mcp_mod, "annotation_reaches", raising)

    async def probe(note: str) -> str:
        """A tool whose only parameter cannot be classified."""
        return note

    with pytest.raises(ValueError, match='"note"'):
        build_mcp_server(_os(probe))


@pytest.mark.parametrize(
    "gate, value",
    [
        ("requires_confirmation", True),
        ("requires_user_input", True),
        ("external_execution", True),
        ("approval_type", "manual"),
    ],
)
async def test_a_gated_function_passed_directly_is_refused_too(gate, value):
    """Every gate in the tuple is inert on this surface, however the Function arrived."""
    gated = Function(name="wipe", entrypoint=lambda path: path, **{gate: value})

    with pytest.raises(ValueError, match=gate):
        build_mcp_server(_os(gated))


async def test_the_refusal_names_every_gate_the_function_sets():
    """The message lists what to drop, not just the first thing found."""
    gated = Function(
        name="wipe",
        entrypoint=lambda path: path,
        requires_confirmation=True,
        external_execution=True,
    )

    with pytest.raises(ValueError) as excinfo:
        build_mcp_server(_os(gated))

    assert "requires_confirmation" in str(excinfo.value)
    assert "external_execution" in str(excinfo.value)
