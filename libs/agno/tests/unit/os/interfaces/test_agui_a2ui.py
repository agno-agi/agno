"""A2UI surface generation over the AG-UI interface."""

import asyncio
import concurrent.futures
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")
pytest.importorskip("ag_ui_a2ui_toolkit", reason="ag_ui_a2ui_toolkit not installed")

from ag_ui_a2ui_toolkit import (  # noqa: E402
    A2UI_SCHEMA_CONTEXT_DESCRIPTION,
    BASIC_CATALOG_ID,
    GENERATE_A2UI_TOOL_NAME,
)
from fastapi.testclient import TestClient  # noqa: E402

from agno.agent import Agent  # noqa: E402
from agno.os.app import AgentOS  # noqa: E402
from agno.os.interfaces.agui import AGUI  # noqa: E402
from agno.os.interfaces.agui import a2ui as a2ui_module  # noqa: E402
from agno.os.interfaces.agui.a2ui import (  # noqa: E402
    OPENAI_RENDER_TOOL_CHOICE,
    RENDER_A2UI_TOOL_NAME,
    A2UIRenderArgumentsError,
    A2UIRenderAttempt,
    agui_state_from_dependencies,
    classify_a2ui_subagent_error,
    get_a2ui_tools,
    stream_render_subagent,
    strip_in_flight_tool_call,
)
from agno.os.interfaces.agui.a2ui_stream import A2UIRenderStream, A2UIRun, current_a2ui_run  # noqa: E402

CATALOG_ID = "declarative-gen-ui-catalog"

VALID_COMPONENTS = [
    {"id": "root", "component": "Column", "children": ["title"]},
    {"id": "title", "component": "Text", "text": "Quarterly sales"},
]

# No component has id "root", so the toolkit's semantic gate rejects the tree.
INVALID_COMPONENTS = [{"id": "orphan", "component": "Text", "text": "nowhere"}]


# =============================================================================
# Test doubles
# =============================================================================


class FakeDelta:
    """One streamed model response carrying tool-call deltas."""

    def __init__(self, tool_calls: Optional[List[Any]] = None) -> None:
        self.tool_calls = tool_calls


class FakeFunctionDelta:
    """A provider tool-call delta in object form (the OpenAI-compatible shape)."""

    def __init__(
        self,
        name: Optional[str] = None,
        arguments: Optional[str] = None,
        index: Optional[int] = None,
        id: Optional[str] = None,
    ) -> None:
        self.function = type("Fn", (), {"name": name, "arguments": arguments})()
        self.index = index
        self.id = id


class ScriptedModel:
    """A model whose render turns are scripted per attempt.

    Each entry in ``script`` is the outcome of one subagent turn: a dict of
    render arguments, ``None`` for "answered without calling the tool", or an
    exception instance to raise.
    """

    assistant_message_role = "assistant"

    def __init__(self, script: List[Any]) -> None:
        self.script = list(script)
        self.calls: List[str] = []
        self.tool_choices: List[Any] = []
        self.seen_messages: List[Any] = []
        self.offered_tools: List[Any] = []

    async def aprocess_response_stream(self, **kwargs: Any) -> AsyncIterator[FakeDelta]:
        prompt = kwargs["messages"][0].content
        self.calls.append(prompt)
        self.seen_messages = list(kwargs["messages"])
        self.offered_tools = list(kwargs.get("tools") or [])
        self.tool_choices.append(kwargs.get("tool_choice"))
        outcome = self.script.pop(0) if self.script else None

        if isinstance(outcome, BaseException):
            raise outcome
        if outcome is None:
            yield FakeDelta()
            return

        # Stream the arguments the way an OpenAI-compatible provider does: a
        # named opening frame, then argument fragments with no name.
        yield FakeDelta([FakeFunctionDelta(name=RENDER_A2UI_TOOL_NAME, arguments="")])
        payload = json.dumps(outcome)
        for start in range(0, len(payload), 16):
            yield FakeDelta([FakeFunctionDelta(arguments=payload[start : start + 16])])


class MisreadDeltaModel:
    """A provider whose argument fragments are not strings.

    Nothing the model did: reading this shape is this module's own job, so the
    failure is raised in a frame of its own rather than in the model layer.
    """

    assistant_message_role = "assistant"

    def __init__(self) -> None:
        self.calls: List[str] = []

    async def aprocess_response_stream(self, **kwargs: Any) -> AsyncIterator[FakeDelta]:
        self.calls.append(kwargs["messages"][0].content)
        yield FakeDelta([FakeFunctionDelta(name=RENDER_A2UI_TOOL_NAME, arguments="")])
        yield FakeDelta([FakeFunctionDelta(arguments=17)])  # type: ignore[arg-type]


class HangingModel:
    """A model whose render turn never answers until the call is cancelled."""

    assistant_message_role = "assistant"

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.calls: List[str] = []

    async def aprocess_response_stream(self, **kwargs: Any) -> AsyncIterator[FakeDelta]:
        self.calls.append(kwargs["messages"][0].content)
        self.started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        yield FakeDelta()


class FakeRunContext:
    def __init__(
        self,
        messages: Optional[List[Any]] = None,
        dependencies: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.messages = messages or []
        self.dependencies = dependencies


def levels_logging(caplog: Any, needle: str) -> set:
    """The levels the records mentioning ``needle`` were logged at.

    A substring match on the text says a line was emitted but not how loudly,
    and a downgrade nobody is told about at the level they watch is the same as
    no downgrade being reported at all.
    """
    return {record.levelname for record in caplog.records if needle in record.getMessage()}


def catalog_component(name: str, *requires: str) -> Dict[str, Any]:
    """One component's schema, in the shape the client's catalog extractor sends.

    Every component is composed with ``allOf`` against the shared component
    base, so the properties it takes and the ones it requires sit a level below
    the entry itself. Written out that way here rather than flattened by hand,
    because a gate that only reads the flattened shape is a gate that never
    runs on a real run.
    """
    return {
        "allOf": [
            {"$ref": "common_types.json#/$defs/ComponentCommon"},
            {
                "properties": {"component": {"const": name}, **{prop: {} for prop in requires}},
                "required": ["component", *requires],
            },
        ]
    }


def forwarded_catalog(**components: Dict[str, Any]) -> Dict[str, Any]:
    """The catalog value the client forwards: component schemas keyed by name."""
    return {"catalogId": CATALOG_ID, "components": components}


def schema_dependencies(catalog_id: str = CATALOG_ID) -> Dict[str, Any]:
    """Dependencies as the AG-UI router builds them from forwarded context."""
    return {
        A2UI_SCHEMA_CONTEXT_DESCRIPTION: {
            "catalogId": catalog_id,
            "components": {"Column": catalog_component("Column"), "Text": catalog_component("Text")},
        },
        "User preferences": {"currency": "USD"},
    }


def prior_surface_envelope(surface_id: str, catalog_id: str = CATALOG_ID) -> str:
    """The tool result an already-rendered surface left behind."""
    return json.dumps(
        {
            "a2ui_operations": [
                {"version": "v0.9", "createSurface": {"surfaceId": surface_id, "catalogId": catalog_id}},
                {
                    "version": "v0.9",
                    "updateComponents": {"surfaceId": surface_id, "components": VALID_COMPONENTS},
                },
            ]
        }
    )


def prior_surface_message(surface_id: str, catalog_id: str = CATALOG_ID) -> Any:
    """A tool result carrying an already-rendered surface, as history replays it."""
    envelope = prior_surface_envelope(surface_id, catalog_id)
    return type("Msg", (), {"role": "tool", "content": envelope, "tool_calls": None})()


def client_surface_message(surface_id: str, catalog_id: str = CATALOG_ID) -> Any:
    """The same surface as the client replays it: a real AG-UI tool message.

    This is the type the router hands the generation tool for a cross-turn
    edit, so the history walk has to read it and not merely something shaped
    like it.
    """
    from ag_ui.core import ToolMessage

    return ToolMessage(
        id=f"msg-{surface_id}",
        role="tool",
        tool_call_id=f"call-{surface_id}",
        content=prior_surface_envelope(surface_id, catalog_id),
    )


async def call_tool(tool: Any, run_context: Any = None, **kwargs: Any) -> Dict[str, Any]:
    """Call a generation tool the way a served run does.

    A real render channel is attached whether or not the caller asked for one,
    because a run that generates a surface always has one: with the channel
    left off, every recovery case here exercised the tool with nothing to push
    to, which is the reason a whole class of streaming defect went unseen.
    """
    existing = current_a2ui_run.get()
    run = A2UIRun(
        render_stream=(existing.render_stream if existing is not None else None) or A2UIRenderStream(),
        state=existing.state if existing is not None else None,
        messages=existing.messages if existing is not None else [],
    )
    token = current_a2ui_run.set(run)
    try:
        raw = await tool.entrypoint(run_context=run_context or FakeRunContext(), **kwargs)
    finally:
        current_a2ui_run.reset(token)
    return json.loads(raw)


async def call_tool_over_the_channel(tool: Any, run_context: Any = None, **kwargs: Any) -> Any:
    """Call a generation tool and collect what it painted as well as what it committed.

    The two are chosen at different sites from different inputs, and a server
    that logs a generated surface while the client shows none is what every
    disagreement between them looks like.
    """
    render_stream = A2UIRenderStream()
    existing = current_a2ui_run.get()
    run = A2UIRun(
        render_stream=render_stream,
        state=existing.state if existing is not None else None,
        messages=existing.messages if existing is not None else [],
    )
    token = current_a2ui_run.set(run)
    try:
        raw = await tool.entrypoint(run_context=run_context or FakeRunContext(), **kwargs)
    finally:
        current_a2ui_run.reset(token)
    return json.loads(raw), render_stream.drain()


def painted_calls(pushed: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Each painted render call as a progressively painting client buffers it.

    Buffered per wire id, because that is the key the AG-UI client's reducer
    buffers argument fragments on: two attempts sharing an id are one buffer
    holding both sets of arguments, which parses as nothing and paints
    nothing.
    """
    order: List[str] = []
    starts: Dict[str, int] = {}
    buffers: Dict[str, str] = {}
    for event in pushed:
        call_id = event["tool_call_id"]
        if event["kind"] == "start":
            if call_id not in order:
                order.append(call_id)
                buffers[call_id] = ""
            starts[call_id] = starts.get(call_id, 0) + 1
        elif event["kind"] == "args":
            buffers[call_id] += event["delta"]
    return [{"call_id": call_id, "starts": starts[call_id], "args": buffers[call_id]} for call_id in order]


async def wait_until(predicate: Any, timeout: float = 5.0) -> None:
    """Poll a cross-thread condition without blocking the event loop."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition never became true")
        await asyncio.sleep(0.01)


def operation_kinds(envelope: Dict[str, Any]) -> List[str]:
    """The operation names in an envelope, in order."""
    kinds = []
    for operation in envelope.get("a2ui_operations", []):
        kinds.extend(key for key in operation if key != "version")
    return kinds


def operation(envelope: Dict[str, Any], kind: str) -> Dict[str, Any]:
    for entry in envelope["a2ui_operations"]:
        if kind in entry:
            return entry[kind]
    raise AssertionError(f"envelope has no {kind} operation: {envelope}")


# =============================================================================
# Tool construction
# =============================================================================


def test_requires_a_model():
    with pytest.raises(ValueError, match="requires a 'model'"):
        get_a2ui_tools({})


def test_advertises_the_shared_tool_contract():
    tool = get_a2ui_tools({"model": ScriptedModel([])})

    assert tool.name == GENERATE_A2UI_TOOL_NAME
    assert tool.description
    assert set(tool.parameters["properties"]) == {"intent", "target_surface_id", "changes"}
    assert tool.parameters["properties"]["intent"]["enum"] == ["create", "update"]
    for spec in tool.parameters["properties"].values():
        assert spec["description"]


def test_honours_a_custom_tool_name():
    tool = get_a2ui_tools({"model": ScriptedModel([]), "tool_name": "draw_ui"})

    assert tool.name == "draw_ui"


def test_warns_on_snake_case_recovery_options(caplog):
    get_a2ui_tools({"model": ScriptedModel([]), "recovery": {"max_attempts": 2}})

    assert "maxAttempts" in caplog.text


def test_nothing_is_forced_by_default():
    """Agno hands ``tool_choice`` to each provider unchanged, and no single
    spelling is accepted everywhere, so the default forces nothing."""
    model = ScriptedModel([{"surfaceId": "s", "components": VALID_COMPONENTS}])
    tool = get_a2ui_tools({"model": model})

    asyncio.run(call_tool(tool))

    assert model.tool_choices == [None]


def test_a_provider_specific_tool_choice_overrides_the_default():
    model = ScriptedModel([{"surfaceId": "s", "components": VALID_COMPONENTS}])
    tool = get_a2ui_tools({"model": model}, {"tool_choice": "any"})

    asyncio.run(call_tool(tool))

    assert model.tool_choices == ["any"]


def test_the_openai_forced_shape_is_available_to_opt_in_to():
    model = ScriptedModel([{"surfaceId": "s", "components": VALID_COMPONENTS}])
    tool = get_a2ui_tools({"model": model}, {"tool_choice": OPENAI_RENDER_TOOL_CHOICE})

    asyncio.run(call_tool(tool))

    assert model.tool_choices == [{"type": "function", "function": {"name": RENDER_A2UI_TOOL_NAME}}]


def test_agnos_synchronous_tool_path_is_refused_rather_than_answered_with_a_coroutine():
    """An async-only entrypoint on the sync path "succeeds" with a coroutine.

    Agno's synchronous tool path calls the entrypoint and keeps what comes
    back, so a developer who wires this onto an agent they drive with run() or
    print_response() has the repr of an un-awaited coroutine sent to their
    model as the tool result.
    """
    from agno.exceptions import AgentRunException
    from agno.tools.function import FunctionCall

    model = ScriptedModel([{"surfaceId": "s", "components": VALID_COMPONENTS}])
    call = FunctionCall(function=get_a2ui_tools({"model": model}), arguments={})

    with pytest.raises(AgentRunException, match="asynchronous"):
        call.execute()

    # The model is told the tool failed, and why, rather than being handed a
    # successful result it cannot read.
    assert "aprint_response" in (call.error or "")
    assert model.calls == []


@pytest.mark.asyncio
async def test_the_asynchronous_tool_path_still_runs_the_whole_call():
    """The same guard runs on both paths, and must only refuse the one."""
    from agno.tools.function import FunctionCall

    model = ScriptedModel([{"surfaceId": "sales", "components": VALID_COMPONENTS}])
    call = FunctionCall(function=get_a2ui_tools({"model": model}), arguments={})

    result = await call.aexecute()

    assert result.status == "success"
    assert operation(json.loads(result.result), "createSurface")["surfaceId"] == "sales"


@pytest.mark.parametrize(
    ("err", "phrase"),
    [
        (ModuleNotFoundError("No module named 'ag_ui_a2ui_toolkit'", name="ag_ui_a2ui_toolkit"), "not installed"),
        (ModuleNotFoundError("No module named 'jsonschema'", name="jsonschema"), "does not have"),
        (ImportError("cannot import name 'resolve_a2ui_catalog'"), "out of date"),
    ],
    ids=["toolkit-absent", "dependency-absent", "symbol-absent"],
)
def test_a_failed_toolkit_import_names_the_fix_it_needs(err, phrase):
    """Three failures, three fixes. A dependency of the toolkit that this
    environment lacks is not the toolkit being out of date, and sending
    someone to upgrade a package that is already current leaves them stuck."""
    message = a2ui_module._toolkit_import_message(err)

    assert phrase in message
    if isinstance(err, ModuleNotFoundError) and err.name != "ag_ui_a2ui_toolkit":
        assert err.name in message


# =============================================================================
# Generation
# =============================================================================


@pytest.mark.asyncio
async def test_creates_a_surface_from_the_subagent_output():
    model = ScriptedModel([{"surfaceId": "sales", "components": VALID_COMPONENTS, "data": {"n": 1}}])
    tool = get_a2ui_tools({"model": model})

    envelope = await call_tool(tool, FakeRunContext(dependencies=schema_dependencies()))

    assert operation_kinds(envelope) == ["createSurface", "updateComponents", "updateDataModel"]
    assert operation(envelope, "createSurface")["surfaceId"] == "sales"
    assert operation(envelope, "updateComponents")["components"] == VALID_COMPONENTS
    assert operation(envelope, "updateDataModel")["value"] == {"n": 1}


@pytest.mark.asyncio
async def test_the_subagent_is_offered_the_render_tool():
    """The one tool the render turn exists to have called.

    Offered nothing, a real provider has no tool to call and every attempt
    ends as a sub-agent that produced no surface, while a scripted model
    streams a render call regardless and the whole suite stays green.
    """
    model = ScriptedModel([{"surfaceId": "s", "components": VALID_COMPONENTS}])
    tool = get_a2ui_tools({"model": model})

    await call_tool(tool)

    assert [offered["function"]["name"] for offered in model.offered_tools] == [RENDER_A2UI_TOOL_NAME]


@pytest.mark.asyncio
async def test_the_in_flight_generation_call_never_reaches_the_subagent():
    """The assistant turn calling the generation tool has no result yet.

    The sub-agent is not offered that tool, so an unanswered call to it is
    malformed input for every provider that checks the pairing, and the render
    turn fails on the provider rather than on anything the model wrote.
    """
    history = [
        {"role": "user", "content": "make a card"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"function": {"name": GENERATE_A2UI_TOOL_NAME}}],
        },
    ]
    model = ScriptedModel([{"surfaceId": "s", "components": VALID_COMPONENTS}])
    tool = get_a2ui_tools({"model": model})

    await call_tool(tool, FakeRunContext(messages=history))

    assert [message for message in model.seen_messages if isinstance(message, dict)] == history[:1]


@pytest.mark.asyncio
async def test_binds_the_surface_to_the_catalog_the_client_registered():
    model = ScriptedModel([{"surfaceId": "s", "components": VALID_COMPONENTS}])
    tool = get_a2ui_tools({"model": model})

    envelope = await call_tool(tool, FakeRunContext(dependencies=schema_dependencies()))

    assert operation(envelope, "createSurface")["catalogId"] == CATALOG_ID


@pytest.mark.asyncio
async def test_falls_back_to_the_basic_catalog_without_forwarded_context():
    model = ScriptedModel([{"surfaceId": "s", "components": VALID_COMPONENTS}])
    tool = get_a2ui_tools({"model": model})

    envelope = await call_tool(tool)

    assert operation(envelope, "createSurface")["catalogId"] == BASIC_CATALOG_ID


@pytest.mark.asyncio
async def test_a_configured_catalog_beats_the_forwarded_one():
    model = ScriptedModel([{"surfaceId": "s", "components": VALID_COMPONENTS}])
    tool = get_a2ui_tools({"model": model, "default_catalog_id": "chosen-by-the-host"})

    envelope = await call_tool(tool, FakeRunContext(dependencies=schema_dependencies()))

    assert operation(envelope, "createSurface")["catalogId"] == "chosen-by-the-host"


@pytest.mark.asyncio
async def test_the_subagent_prompt_carries_the_catalog_and_the_context():
    model = ScriptedModel([{"surfaceId": "s", "components": VALID_COMPONENTS}])
    tool = get_a2ui_tools({"model": model})

    await call_tool(tool, FakeRunContext(dependencies=schema_dependencies()))

    prompt = model.calls[0]
    assert "## Available Components" in prompt
    assert '"Column"' in prompt
    assert "## User preferences" in prompt


@pytest.mark.asyncio
async def test_updating_a_prior_surface_reuses_it_in_place():
    model = ScriptedModel([{"surfaceId": "ignored", "components": VALID_COMPONENTS}])
    tool = get_a2ui_tools({"model": model})
    context = FakeRunContext(messages=[prior_surface_message("sales")])

    envelope = await call_tool(tool, context, intent="update", target_surface_id="sales", changes="make it red")

    # No createSurface: the client reconciles the surface it already has.
    assert operation_kinds(envelope) == ["updateComponents"]
    assert operation(envelope, "updateComponents")["surfaceId"] == "sales"
    prompt = model.calls[0]
    assert "Editing an existing surface" in prompt
    assert "make it red" in prompt


@pytest.mark.asyncio
async def test_a_surface_from_an_earlier_turn_is_edited_in_place():
    """The cross-turn edit, against the message type the client really sends.

    The agent's own run history covers only the turn in progress, so a surface
    from an earlier turn is found in what the client replayed, and those are
    AG-UI messages rather than anything this package built.
    """
    model = ScriptedModel([{"surfaceId": "ignored", "components": VALID_COMPONENTS}])
    tool = get_a2ui_tools({"model": model})
    run = A2UIRun(messages=[client_surface_message("sales")])

    token = current_a2ui_run.set(run)
    try:
        envelope = await call_tool(tool, intent="update", target_surface_id="sales", changes="make it red")
    finally:
        current_a2ui_run.reset(token)

    assert operation_kinds(envelope) == ["updateComponents"]
    assert operation(envelope, "updateComponents")["surfaceId"] == "sales"
    assert "Editing an existing surface" in model.calls[0]


@pytest.mark.asyncio
async def test_updating_an_unknown_surface_fails_without_calling_the_model():
    model = ScriptedModel([{"surfaceId": "s", "components": VALID_COMPONENTS}])
    tool = get_a2ui_tools({"model": model})

    envelope = await call_tool(tool, intent="update", target_surface_id="never-rendered")

    assert "no prior render" in envelope["error"]
    assert model.calls == []


@pytest.mark.asyncio
async def test_an_update_that_names_no_surface_creates_one():
    """An edit with nothing to edit is served as a fresh surface.

    ``target_surface_id`` is optional because it has to be: a provider in
    strict mode reads a missing ``required`` as "all of them" and could not
    create a surface at all. So a model can ask to update and name nothing,
    and the useful answer is the surface it was asked for rather than an error
    the user sees as a turn that produced nothing.
    """
    # Deliberately not the prior surface's id: "created from the model's own id"
    # and "silently reused the prior surface" are otherwise the same assertion.
    model = ScriptedModel([{"surfaceId": "fresh", "components": VALID_COMPONENTS}])
    tool = get_a2ui_tools({"model": model})
    context = FakeRunContext(messages=[prior_surface_message("sales")])

    envelope = await call_tool(tool, context, intent="update", changes="make it red")

    assert operation_kinds(envelope) == ["createSurface", "updateComponents"]
    assert operation(envelope, "createSurface")["surfaceId"] == "fresh"
    assert operation(envelope, "updateComponents")["surfaceId"] == "fresh"
    assert len(model.calls) == 1


@pytest.mark.asyncio
async def test_an_intent_outside_the_enum_creates_a_surface():
    """The tool advertises create and update, and a provider that ignores the
    enum still gets a renderable answer instead of taking the run down. Only
    an update names a surface to reuse, so anything else creates one."""
    model = ScriptedModel([{"surfaceId": "fresh", "components": VALID_COMPONENTS}])
    tool = get_a2ui_tools({"model": model})
    context = FakeRunContext(messages=[prior_surface_message("sales")])

    envelope = await call_tool(tool, context, intent="destroy", target_surface_id="sales")

    assert operation_kinds(envelope) == ["createSurface", "updateComponents"]
    assert operation(envelope, "createSurface")["surfaceId"] == "fresh"
    assert operation(envelope, "updateComponents")["surfaceId"] == "fresh"


# =============================================================================
# Recovery
# =============================================================================


@pytest.mark.asyncio
async def test_an_invalid_surface_is_retried_and_only_the_valid_one_is_committed():
    model = ScriptedModel(
        [
            {"surfaceId": "s", "components": INVALID_COMPONENTS},
            {"surfaceId": "s", "components": VALID_COMPONENTS},
        ]
    )
    attempts: List[Dict[str, Any]] = []
    tool = get_a2ui_tools({"model": model, "on_a2ui_attempt": attempts.append})

    envelope = await call_tool(tool)

    assert operation(envelope, "updateComponents")["components"] == VALID_COMPONENTS
    assert [entry["ok"] for entry in attempts] == [False, True]


@pytest.mark.asyncio
async def test_a_retry_tells_the_subagent_what_was_wrong():
    model = ScriptedModel(
        [
            {"surfaceId": "s", "components": INVALID_COMPONENTS},
            {"surfaceId": "s", "components": VALID_COMPONENTS},
        ]
    )
    tool = get_a2ui_tools({"model": model})

    await call_tool(tool)

    assert "Previous attempt was invalid" not in model.calls[0]
    assert "Previous attempt was invalid" in model.calls[1]


@pytest.mark.asyncio
async def test_a_component_the_client_cannot_draw_is_retried_rather_than_committed():
    """The retry gate applies the rule the client's paint gate applies.

    The renderer validates against the catalog it registered, so it refuses a
    component that catalog does not define. Checked for structure only, such a
    tree passes here, is committed, and is then refused by the browser with no
    attempt left to heal it and nothing said on either side.
    """
    unknown = [{"id": "root", "component": "Sparkline", "series": [1, 2]}]
    model = ScriptedModel(
        [
            {"surfaceId": "s", "components": unknown},
            {"surfaceId": "s", "components": VALID_COMPONENTS},
        ]
    )
    attempts: List[Dict[str, Any]] = []
    tool = get_a2ui_tools({"model": model, "on_a2ui_attempt": attempts.append})

    envelope = await call_tool(tool, FakeRunContext(dependencies=schema_dependencies()))

    assert [entry["ok"] for entry in attempts] == [False, True]
    assert [error["code"] for error in attempts[0]["errors"]] == ["unknown_component"]
    assert operation(envelope, "updateComponents")["components"] == VALID_COMPONENTS


@pytest.mark.asyncio
async def test_a_component_missing_a_property_its_catalog_requires_is_retried():
    """The second half of the client's rule: required props, per component.

    What each component requires is stated inside its ``allOf`` composition, so
    a gate that reads the entry only at its top level finds every component
    requiring nothing and this half of the rule never fires.
    """
    dependencies = {
        A2UI_SCHEMA_CONTEXT_DESCRIPTION: forwarded_catalog(
            Column=catalog_component("Column"),
            Text=catalog_component("Text", "text"),
        )
    }
    model = ScriptedModel(
        [
            {"surfaceId": "s", "components": [{"id": "root", "component": "Text"}]},
            {"surfaceId": "s", "components": VALID_COMPONENTS},
        ]
    )
    attempts: List[Dict[str, Any]] = []
    tool = get_a2ui_tools({"model": model, "on_a2ui_attempt": attempts.append})

    envelope = await call_tool(tool, FakeRunContext(dependencies=dependencies))

    assert [error["code"] for error in attempts[0]["errors"]] == ["missing_required_prop"]
    assert operation(envelope, "updateComponents")["components"] == VALID_COMPONENTS


@pytest.mark.asyncio
async def test_a_catalog_the_host_pinned_beats_the_forwarded_one_at_the_gate():
    """A host that hard-coded a catalog has said what it will draw.

    Its own components are the ones to validate against, so a run whose client
    forwarded a different schema is still gated on the host's choice.
    """
    model = ScriptedModel([{"surfaceId": "s", "components": [{"id": "root", "component": "Sparkline"}]}])
    tool = get_a2ui_tools({"model": model, "catalog": {"components": {"Sparkline": {}}}})

    envelope = await call_tool(tool, FakeRunContext(dependencies=schema_dependencies()))

    assert operation(envelope, "updateComponents")["components"][0]["component"] == "Sparkline"


@pytest.mark.parametrize(
    "state",
    [None, {}, {"ag-ui": {}}, {"ag-ui": {"a2ui_schema": ""}}],
    ids=["no-state", "no-ag-ui", "no-schema", "empty-schema"],
)
def test_a_run_that_forwarded_no_schema_says_nothing_about_it(state, caplog):
    """Nothing was forwarded, so there is nothing to report about it.

    A host that never wired a catalog is not running a degraded gate, it is
    running the only gate available, and warning per generation about it would
    train an operator to read past the warnings that do mean something.
    """
    assert a2ui_module.forwarded_a2ui_catalog(state) is None
    assert levels_logging(caplog, "A2UI component schema") == set()


@pytest.mark.parametrize(
    "schema",
    [
        "{not json",
        json.dumps({"catalogId": "c"}),
        json.dumps({"components": "Column, Text"}),
        json.dumps({"components": {}}),
        json.dumps({"components": {"Text": "not a schema"}}),
        json.dumps([{"name": "Column"}, {"name": "Text"}]),
        json.dumps({"components": [{"name": "Column"}, {"name": "Text"}]}),
    ],
    ids=[
        "not-json",
        "no-components",
        "components-a-string",
        "no-components-at-all",
        "no-readable-component",
        "legacy-array",
        "legacy-list",
    ],
)
def test_a_schema_that_names_no_components_leaves_the_structural_gate_standing(schema, caplog):
    """A gate weaker than the client's still beats no generation at all.

    None of these shapes keys component schemas by name, which is the only
    shape the client's own middleware builds a validation catalog from: the
    legacy array forms degrade to structural checks there too, so degrading
    here is parity and converting them would make this gate the stricter of
    the two. Every one of them is said out loud, because a silent downgrade is
    how a gate comes to look like it is running when it is not.
    """
    assert a2ui_module.forwarded_a2ui_catalog({"ag-ui": {"a2ui_schema": schema}}) is None
    assert levels_logging(caplog, "A2UI component schema") == {"WARNING"}


def test_the_forwarded_catalog_is_read_with_its_composition_flattened(caplog):
    """The client keys components by name and composes each one with ``allOf``.

    The shared validator reads ``required`` and ``properties`` off the top of
    an entry, so the composition has to be flattened into it or a component
    that requires a property is indistinguishable from one that requires none.
    A catalog this can read is also the ordinary case, and says nothing.
    """
    state = {"ag-ui": {"a2ui_schema": json.dumps(forwarded_catalog(Text=catalog_component("Text", "text")))}}

    catalog = a2ui_module.forwarded_a2ui_catalog(state)

    assert catalog is not None
    assert catalog["components"]["Text"]["required"] == ["component", "text"]
    assert set(catalog["components"]["Text"]["properties"]) == {"component", "text"}
    assert levels_logging(caplog, "A2UI component schema") == set()


def test_a_catalog_already_flat_is_left_as_it_is():
    """A host or client that sends a plain JSON Schema per component is read too."""
    flat = {"Text": {"type": "object", "properties": {"text": {}}, "required": ["text"]}}
    state = {"ag-ui": {"a2ui_schema": {"catalogId": CATALOG_ID, "components": flat}}}

    assert a2ui_module.forwarded_a2ui_catalog(state) == {"components": flat}


def test_a_schema_forwarded_as_a_mapping_is_read_without_a_round_trip():
    """The router hands state a JSON string, a hand-wired run a dict."""
    schema = forwarded_catalog(Text=catalog_component("Text"))

    catalog = a2ui_module.forwarded_a2ui_catalog({"ag-ui": {"a2ui_schema": schema}})

    assert catalog is not None
    assert list(catalog["components"]) == ["Text"]


@pytest.mark.asyncio
async def test_a_failing_update_leaves_the_prior_surface_untouched():
    model = ScriptedModel([{"surfaceId": "s", "components": INVALID_COMPONENTS}] * 3)
    tool = get_a2ui_tools({"model": model})
    context = FakeRunContext(messages=[prior_surface_message("sales")])

    envelope = await call_tool(tool, context, intent="update", target_surface_id="sales")

    # A hard failure carries no operations at all, so nothing overwrites what
    # is already on screen.
    assert envelope["code"] == "a2ui_recovery_exhausted"
    assert "a2ui_operations" not in envelope


@pytest.mark.asyncio
async def test_repeated_invalid_surfaces_fail_cleanly_within_the_attempt_cap():
    model = ScriptedModel([{"surfaceId": "s", "components": INVALID_COMPONENTS}] * 5)
    tool = get_a2ui_tools({"model": model})

    envelope = await call_tool(tool)

    assert envelope["code"] == "a2ui_recovery_exhausted"
    assert len(envelope["attempts"]) == 3
    assert len(model.calls) == 3


@pytest.mark.asyncio
async def test_the_attempt_cap_is_configurable():
    model = ScriptedModel([{"surfaceId": "s", "components": INVALID_COMPONENTS}] * 5)
    tool = get_a2ui_tools({"model": model, "recovery": {"maxAttempts": 2}})

    envelope = await call_tool(tool)

    assert len(envelope["attempts"]) == 2
    assert len(model.calls) == 2


@pytest.mark.asyncio
async def test_a_subagent_that_never_calls_the_render_tool_counts_as_a_failed_attempt():
    model = ScriptedModel([None, {"surfaceId": "s", "components": VALID_COMPONENTS}])
    tool = get_a2ui_tools({"model": model})

    envelope = await call_tool(tool)

    assert operation(envelope, "updateComponents")["components"] == VALID_COMPONENTS
    assert len(model.calls) == 2


@pytest.mark.asyncio
async def test_a_model_failure_is_retried_rather_than_surfaced():
    model = ScriptedModel([RuntimeError("429 rate limited"), {"surfaceId": "s", "components": VALID_COMPONENTS}])
    tool = get_a2ui_tools({"model": model})

    envelope = await call_tool(tool)

    assert operation(envelope, "updateComponents")["components"] == VALID_COMPONENTS


@pytest.mark.asyncio
async def test_a_mistake_in_this_adapter_is_not_swallowed_as_a_bad_surface():
    """A delta shape this module misreads comes out of a frame of its own.

    Retried as if the model had produced a bad surface it would burn every
    attempt and then be reported to the model as a sub-agent that never called
    the render tool, which hides the real bug entirely.
    """
    model = MisreadDeltaModel()
    tool = get_a2ui_tools({"model": model})

    with pytest.raises(TypeError):
        await call_tool(tool)

    assert len(model.calls) == 1


def test_cancellation_is_recognized_whichever_packages_class_it_arrives_as():
    """Why the cancellation guard names two classes rather than one.

    The recovery loop runs on a thread and waits on a ``concurrent.futures``
    future, so a cancelled render call arrives as that package's own
    ``CancelledError``. The two library facts below are what make the second
    entry load-bearing, and both would go unnoticed: an ``except
    asyncio.CancelledError`` never sees a cross-thread cancel, and a bare
    ``except Exception`` swallows one as if it were a model failure and retries
    it after the caller has already gone.
    """
    assert a2ui_module._is_a2ui_cancellation(asyncio.CancelledError())
    assert a2ui_module._is_a2ui_cancellation(concurrent.futures.CancelledError())

    assert not issubclass(concurrent.futures.CancelledError, asyncio.CancelledError)
    assert issubclass(concurrent.futures.CancelledError, Exception)


def test_the_classes_that_mean_this_adapter_is_wrong_are_enumerated():
    """Named exactly, so adding or removing one is a diff rather than a judgement.

    These decide an exception that carries no traceback to read an origin
    from. Each unwinds the tool call without consuming a retry, which is the
    right answer only for a failure this module itself caused; every one of
    them also arises in the model layer and the provider SDK, which is why an
    exception raised for real is judged by where it came from instead.
    """
    assert a2ui_module._A2UI_ADAPTER_BUG_ERRORS == (
        TypeError,
        NameError,
        AttributeError,
        KeyError,
        IndexError,
        ImportError,
        AssertionError,
    )


@pytest.mark.parametrize(
    ("err", "verdict"),
    [
        (asyncio.CancelledError(), "rethrow"),
        (concurrent.futures.CancelledError(), "rethrow"),
        (KeyboardInterrupt(), "rethrow"),
        (SystemExit(), "rethrow"),
        (TypeError(), "rethrow"),
        (NameError(), "rethrow"),
        (AttributeError(), "rethrow"),
        (KeyError(), "rethrow"),
        (IndexError(), "rethrow"),
        (ImportError(), "rethrow"),
        (AssertionError(), "rethrow"),
        (RuntimeError(), "recoverable"),
        (ValueError(), "recoverable"),
        (TimeoutError(), "recoverable"),
        (asyncio.TimeoutError(), "recoverable"),
        (json.JSONDecodeError("bad", "{", 0), "recoverable"),
    ],
    ids=[
        "asyncio-cancelled",
        "cross-thread-cancelled",
        "keyboard-interrupt",
        "system-exit",
        "type",
        "name",
        "attribute",
        "key",
        "index",
        "import",
        "assertion",
        "runtime",
        "value",
        "timeout",
        "asyncio-timeout",
        "json-decode",
    ],
)
def test_every_class_the_classifier_can_see_has_a_pinned_verdict(err, verdict):
    """One row per class this module raises, names, or receives across a thread.

    Constructed rather than raised, so none of them carries a traceback: these
    are the verdicts the fallback earns when there is no origin to read. Where
    each class comes from when it is raised for real is pinned below.
    """
    assert classify_a2ui_subagent_error(err) == verdict


def test_where_an_exception_was_raised_decides_it_when_the_traceback_says():
    """The same class earns opposite verdicts depending on where it came from.

    ``AttributeError`` is as much a provider-SDK failure as an adapter bug.
    Read by class alone, a provider-side one kills the run without even
    costing an attempt, and an adapter-side one is retried three times and
    then blamed on the model.
    """
    # Through ``pytest.raises`` rather than caught by hand: a call that stops
    # raising is then reported as exactly that, instead of as a NameError from
    # the name below never being bound.
    with pytest.raises(AttributeError) as from_elsewhere:
        raise AttributeError("raised where the model layer lives")

    with pytest.raises(AttributeError) as from_this_module:
        a2ui_module._parse_render_arguments(None)  # type: ignore[arg-type]

    assert classify_a2ui_subagent_error(from_elsewhere.value) == "recoverable"
    assert a2ui_module._raised_in_this_module(from_elsewhere.value) is False
    assert a2ui_module._raised_in_this_module(from_this_module.value) is True
    assert a2ui_module._raised_in_this_module(AttributeError()) is None


def test_the_failures_this_module_raises_on_purpose_still_cost_only_an_attempt():
    """Origin alone would read these as bugs; they are attempt outcomes.

    Unusable arguments and a render turn past its deadline are both raised
    from this module's own frames in order to end one attempt and be tried
    again, so they have to outrank the origin rule that would kill the run.
    """
    with pytest.raises(A2UIRenderArgumentsError) as unusable_arguments:
        a2ui_module._parse_render_arguments("   ")

    pending: "concurrent.futures.Future" = concurrent.futures.Future()
    loop = asyncio.new_event_loop()
    try:
        with pytest.raises(TimeoutError) as outran_its_deadline:
            a2ui_module._wait_for_a2ui_subagent(pending, threading.Event(), loop, timeout=0.0)
    finally:
        loop.close()

    for raised in (unusable_arguments.value, outran_its_deadline.value):
        assert a2ui_module._raised_in_this_module(raised) is True
        assert classify_a2ui_subagent_error(raised) == "recoverable"


def test_a_cross_thread_cancellation_is_not_reported_as_a_recovery_failure(caplog):
    """The abandoned-recovery report reads cancellation by the same twin.

    Cancelling the wait cancels the worker's future, so the error the callback
    finds there is the caller's own cancellation. Reported as a failure it puts
    a warning in the log for every ordinary disconnect.
    """
    worker: "concurrent.futures.Future" = concurrent.futures.Future()
    worker.set_running_or_notify_cancel()
    worker.set_exception(concurrent.futures.CancelledError())

    a2ui_module._log_abandoned_recovery(worker)

    assert "recovery loop failed" not in caplog.text


@pytest.mark.parametrize(
    "err",
    [
        AttributeError("'Fn' object has no attribute 'name'"),
        KeyError("choices"),
        ImportError("no module named 'httpx'"),
    ],
    ids=["attribute", "key", "import"],
)
async def test_a_provider_side_shape_error_costs_one_attempt_rather_than_the_run(err):
    """The model layer and the provider SDK raise these too.

    Treated as this adapter's own bug, a transient one inside the provider
    call unwinds the whole tool call without even trying again, so a run that
    a second attempt would have completed produces nothing at all.
    """
    model = ScriptedModel([err, {"surfaceId": "s", "components": VALID_COMPONENTS}])
    tool = get_a2ui_tools({"model": model})

    envelope = await call_tool(tool)

    assert operation(envelope, "updateComponents")["components"] == VALID_COMPONENTS
    assert len(model.calls) == 2


@pytest.mark.parametrize(
    "err",
    [
        AttributeError("'Fn' object has no attribute 'name'"),
        RuntimeError("401 invalid api key"),
        A2UIRenderArgumentsError("the render arguments were not valid JSON"),
    ],
    ids=["shape", "auth", "arguments"],
)
async def test_the_next_attempt_is_told_what_really_went_wrong(err):
    """The shared loop can only say the sub-agent did not call the render tool.

    That is the whole account the next attempt gets, and for a transport
    failure or arguments that could not be read it is not vague but wrong.
    """
    model = ScriptedModel([err, {"surfaceId": "s", "components": VALID_COMPONENTS}])
    tool = get_a2ui_tools({"model": model})

    await call_tool(tool)

    assert str(err) not in model.calls[0]
    assert str(err) in model.calls[1]


async def test_a_provider_failure_reaches_the_tool_result():
    """A 401 is not a bad surface, and must not be reported as one."""
    # One instance per attempt, as a provider raises them. Re-raising a single
    # object accumulates a traceback and an exception context across attempts,
    # which is state the origin rule reads.
    model = ScriptedModel([RuntimeError("401 invalid api key") for _ in range(3)])
    tool = get_a2ui_tools({"model": model})

    envelope = await call_tool(tool)

    assert envelope["code"] == "a2ui_recovery_exhausted"
    assert any("401 invalid api key" in cause for cause in envelope["subagentErrors"])


# =============================================================================
# Concurrency, hangs and disconnects
# =============================================================================


def test_generation_does_not_compete_for_the_shared_thread_pool():
    """A generation waits on model calls, so it must not park in the pool the
    rest of the process shares.

    On a loop of its own, because there is no way to give a loop its default
    executor back: leaving a shut-down pool installed on a loop anything else
    reaches would break every later ``run_in_executor`` on it.
    """

    async def occupy_the_default_pool_and_generate() -> None:
        loop = asyncio.get_running_loop()
        shared_pool = ThreadPoolExecutor(max_workers=1)
        loop.set_default_executor(shared_pool)
        release = threading.Event()
        occupied = loop.run_in_executor(None, release.wait)

        try:
            model = ScriptedModel([{"surfaceId": "s", "components": VALID_COMPONENTS}])
            tool = get_a2ui_tools({"model": model})

            envelope = await asyncio.wait_for(call_tool(tool), timeout=5)

            assert operation(envelope, "updateComponents")["components"] == VALID_COMPONENTS
        finally:
            release.set()
            await occupied
            shared_pool.shutdown(wait=True)

    asyncio.run(occupy_the_default_pool_and_generate())


async def test_a_hung_subagent_call_is_given_up_on():
    model = HangingModel()
    tool = get_a2ui_tools({"model": model, "recovery": {"maxAttempts": 1}}, {"subagent_timeout": 0.2})

    envelope = await asyncio.wait_for(call_tool(tool), timeout=10)

    assert envelope["code"] == "a2ui_recovery_exhausted"
    assert any("did not answer" in cause for cause in envelope["subagentErrors"])
    # The abandoned call is cancelled, not left streaming into nothing.
    await asyncio.wait_for(model.cancelled.wait(), timeout=5)


async def test_a_hang_is_bounded_without_any_configuration(monkeypatch):
    monkeypatch.setattr(a2ui_module, "DEFAULT_RENDER_SUBAGENT_TIMEOUT", 0.2)
    model = HangingModel()
    tool = get_a2ui_tools({"model": model, "recovery": {"maxAttempts": 1}})

    envelope = await asyncio.wait_for(call_tool(tool), timeout=10)

    assert envelope["code"] == "a2ui_recovery_exhausted"


async def test_a_disconnect_mid_call_cancels_the_call_and_stops_the_loop():
    model = HangingModel()
    tool = get_a2ui_tools({"model": model})
    task = asyncio.create_task(call_tool(tool))
    await asyncio.wait_for(model.started.wait(), timeout=5)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    await asyncio.wait_for(model.cancelled.wait(), timeout=5)
    assert len(model.calls) == 1


def never_answers() -> "concurrent.futures.Future":
    """A scheduled render turn that neither completes nor can be cancelled promptly."""
    return concurrent.futures.Future()


def wait_for_render_turn(
    pending: "concurrent.futures.Future",
    abandoned: threading.Event,
    loop: asyncio.AbstractEventLoop,
    timeout: Optional[float],
) -> Dict[str, Any]:
    """Run the blocking wait on a thread and report how it ended.

    On a thread rather than inline because every way out of that wait is a
    branch under test: a wait that stops ending has to fail this suite rather
    than wedge it.
    """
    outcome: Dict[str, Any] = {}

    def run() -> None:
        try:
            outcome["result"] = a2ui_module._wait_for_a2ui_subagent(pending, abandoned, loop, timeout)
        except BaseException as err:  # noqa: BLE001 - how it ended is the outcome
            outcome["error"] = err

    worker = threading.Thread(target=run, name="a2ui-wait-probe", daemon=True)
    worker.start()
    worker.join(5)

    assert not worker.is_alive(), "the wait on the render turn never ended"
    return outcome


def test_a_disconnect_is_noticed_while_the_render_turn_is_still_running():
    """The mid-call poll, on its own.

    The wait is broken into polls precisely so a disconnect does not have to
    wait for the provider, and this branch is the only mechanism that can
    notice one mid-call: the caller's own cancel races the bookkeeping that
    would let it reach the call in flight, and the next attempt's check comes a
    whole model turn too late.
    """
    pending = never_answers()
    abandoned = threading.Event()
    abandoned.set()
    loop = asyncio.new_event_loop()

    try:
        outcome = wait_for_render_turn(pending, abandoned, loop, timeout=2.0)
    finally:
        loop.close()

    assert isinstance(outcome.get("error"), asyncio.CancelledError)
    assert "disconnected" in str(outcome["error"])
    # Left running it would stream a surface nobody will ever see.
    assert pending.cancelled()


def test_a_closed_loop_ends_the_wait_the_same_way():
    """Nothing can be scheduled back onto a closed loop, so the turn in flight
    will never answer and the next attempt cannot even start."""
    pending = never_answers()
    loop = asyncio.new_event_loop()
    loop.close()

    outcome = wait_for_render_turn(pending, threading.Event(), loop, timeout=2.0)

    assert isinstance(outcome.get("error"), asyncio.CancelledError)
    assert pending.cancelled()


def test_a_render_turn_past_its_deadline_is_cancelled_and_reported():
    """A provider that never answers would otherwise hold the tool call, and
    the client's whole run, open forever."""
    pending = never_answers()
    loop = asyncio.new_event_loop()

    try:
        outcome = wait_for_render_turn(pending, threading.Event(), loop, timeout=0.2)
    finally:
        loop.close()

    assert isinstance(outcome.get("error"), TimeoutError)
    assert "did not answer within" in str(outcome["error"])
    assert pending.cancelled()


async def test_an_ordinary_failure_is_not_reported_as_a_disconnect(caplog):
    model = MisreadDeltaModel()
    tool = get_a2ui_tools({"model": model})

    with pytest.raises(TypeError):
        await call_tool(tool)
    for _ in range(5):
        await asyncio.sleep(0.01)

    assert "disconnected" not in caplog.text


async def test_a_worker_failure_after_a_disconnect_is_still_logged(caplog):
    """The abandoned loop's own error is the one thing nobody else can report."""
    entered = threading.Event()
    release = threading.Event()

    def record_attempt(_: Dict[str, Any]) -> None:
        entered.set()
        release.wait(5)
        raise RuntimeError("attempt bookkeeping exploded")

    model = ScriptedModel([{"surfaceId": "s", "components": INVALID_COMPONENTS}] * 3)
    tool = get_a2ui_tools({"model": model, "on_a2ui_attempt": record_attempt})
    task = asyncio.create_task(call_tool(tool))
    await wait_until(entered.is_set)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()

    await wait_until(lambda: "attempt bookkeeping exploded" in caplog.text)


# =============================================================================
# Provider delta shapes
# =============================================================================


@pytest.mark.asyncio
async def test_reads_a_whole_call_delivered_in_one_frame():
    """Anthropic and Gemini emit the complete call as a single dict."""

    class SingleFrameModel(ScriptedModel):
        async def aprocess_response_stream(self, **kwargs: Any) -> AsyncIterator[FakeDelta]:
            self.calls.append(kwargs["messages"][0].content)
            yield FakeDelta(
                [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": RENDER_A2UI_TOOL_NAME,
                            "arguments": json.dumps({"surfaceId": "s", "components": VALID_COMPONENTS}),
                        },
                    }
                ]
            )

    tool = get_a2ui_tools({"model": SingleFrameModel([])})

    envelope = await call_tool(tool)

    assert operation(envelope, "updateComponents")["components"] == VALID_COMPONENTS


@pytest.mark.asyncio
async def test_ignores_fragments_belonging_to_another_tool():
    class NoisyModel(ScriptedModel):
        async def aprocess_response_stream(self, **kwargs: Any) -> AsyncIterator[FakeDelta]:
            self.calls.append(kwargs["messages"][0].content)
            yield FakeDelta([FakeFunctionDelta(name="something_else", arguments='{"junk":')])
            yield FakeDelta([FakeFunctionDelta(arguments="1}")])
            yield FakeDelta(
                [
                    FakeFunctionDelta(
                        name=RENDER_A2UI_TOOL_NAME,
                        arguments=json.dumps({"surfaceId": "s", "components": VALID_COMPONENTS}),
                    )
                ]
            )

    tool = get_a2ui_tools({"model": NoisyModel([])})

    envelope = await call_tool(tool)

    assert operation(envelope, "updateComponents")["components"] == VALID_COMPONENTS


@pytest.mark.asyncio
async def test_truncated_arguments_do_not_commit_a_surface():
    class TruncatingModel(ScriptedModel):
        async def aprocess_response_stream(self, **kwargs: Any) -> AsyncIterator[FakeDelta]:
            self.calls.append(kwargs["messages"][0].content)
            yield FakeDelta([FakeFunctionDelta(name=RENDER_A2UI_TOOL_NAME, arguments='{"surfaceId": "s", "comp')])

    tool = get_a2ui_tools({"model": TruncatingModel([]), "recovery": {"maxAttempts": 1}})

    envelope = await call_tool(tool)

    assert envelope["code"] == "a2ui_recovery_exhausted"
    # The shared loop cannot tell arguments it could not read from a
    # sub-agent that never called the render tool, and reports both the
    # second way, so the real cause has to travel separately.
    assert any("not valid JSON" in cause for cause in envelope["subagentErrors"])


@pytest.mark.asyncio
async def test_reads_argument_fragments_from_a_real_provider_stream():
    """Pins the contract this adapter depends on: an OpenAI-compatible model
    surfaces partial render arguments as separate deltas."""
    pytest.importorskip("openai")
    from openai.types.chat import ChatCompletionChunk

    from agno.models.openai import OpenAIChat

    fragments = ['{"surfaceId": "s", "compo', 'nents": ', json.dumps(VALID_COMPONENTS), "}"]

    def chunk(tool_calls):
        return ChatCompletionChunk.model_validate(
            {
                "id": "c",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "m",
                "choices": [{"index": 0, "delta": {"tool_calls": tool_calls}, "finish_reason": None}],
            }
        )

    class StreamingProvider(OpenAIChat):
        async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:  # type: ignore[override]
            yield self._parse_provider_response_delta(
                chunk(
                    [
                        {
                            "index": 0,
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": RENDER_A2UI_TOOL_NAME, "arguments": ""},
                        }
                    ]
                )
            )
            for fragment in fragments:
                yield self._parse_provider_response_delta(chunk([{"index": 0, "function": {"arguments": fragment}}]))

    tool = get_a2ui_tools({"model": StreamingProvider(id="m", api_key="x")})

    envelope = await call_tool(tool)

    assert operation(envelope, "updateComponents")["components"] == VALID_COMPONENTS


@pytest.mark.asyncio
async def test_a_trailing_delta_for_another_tool_keeps_the_finished_surface():
    """A finished surface must survive a provider naming another tool after it."""

    class TrailingEchoModel(ScriptedModel):
        async def aprocess_response_stream(self, **kwargs: Any) -> AsyncIterator[FakeDelta]:
            self.calls.append(kwargs["messages"][0].content)
            yield FakeDelta(
                [
                    FakeFunctionDelta(
                        name=RENDER_A2UI_TOOL_NAME,
                        index=0,
                        id="call_1",
                        arguments=json.dumps({"surfaceId": "s", "components": VALID_COMPONENTS}),
                    )
                ]
            )
            yield FakeDelta([FakeFunctionDelta(name="search_web", index=1, id="call_2", arguments="{}")])

    model = TrailingEchoModel([])
    tool = get_a2ui_tools({"model": model, "recovery": {"maxAttempts": 1}})

    envelope = await call_tool(tool)

    assert operation(envelope, "updateComponents")["components"] == VALID_COMPONENTS
    assert len(model.calls) == 1


@pytest.mark.asyncio
async def test_a_provider_that_repeats_the_tool_name_on_every_frame():
    """ollama and mistral name the tool on every frame of one call, so a name
    alone cannot mean a new call has started."""

    class RepeatsNameModel(ScriptedModel):
        async def aprocess_response_stream(self, **kwargs: Any) -> AsyncIterator[FakeDelta]:
            self.calls.append(kwargs["messages"][0].content)
            payload = json.dumps({"surfaceId": "s", "components": VALID_COMPONENTS})
            for start in range(0, len(payload), 16):
                yield FakeDelta(
                    [
                        FakeFunctionDelta(
                            name=RENDER_A2UI_TOOL_NAME,
                            index=0,
                            arguments=payload[start : start + 16],
                        )
                    ]
                )

    tool = get_a2ui_tools({"model": RepeatsNameModel([]), "recovery": {"maxAttempts": 1}})

    envelope = await call_tool(tool)

    assert operation(envelope, "updateComponents")["components"] == VALID_COMPONENTS


@pytest.mark.asyncio
async def test_an_empty_tool_name_on_a_continuation_frame_is_ignored():
    """Some providers echo an empty name on continuation frames."""

    class EmptyNameModel(ScriptedModel):
        async def aprocess_response_stream(self, **kwargs: Any) -> AsyncIterator[FakeDelta]:
            self.calls.append(kwargs["messages"][0].content)
            payload = json.dumps({"surfaceId": "s", "components": VALID_COMPONENTS})
            yield FakeDelta([FakeFunctionDelta(name=RENDER_A2UI_TOOL_NAME, index=0, arguments=payload[:16])])
            yield FakeDelta([FakeFunctionDelta(name="", index=0, arguments=payload[16:])])

    tool = get_a2ui_tools({"model": EmptyNameModel([]), "recovery": {"maxAttempts": 1}})

    envelope = await call_tool(tool)

    assert operation(envelope, "updateComponents")["components"] == VALID_COMPONENTS


@pytest.mark.asyncio
async def test_a_provider_that_repeats_the_name_and_identifies_no_call():
    """Same repetition, but with neither an index nor an id to key on."""

    class BareRepeatsNameModel(ScriptedModel):
        async def aprocess_response_stream(self, **kwargs: Any) -> AsyncIterator[FakeDelta]:
            self.calls.append(kwargs["messages"][0].content)
            payload = json.dumps({"surfaceId": "s", "components": VALID_COMPONENTS})
            for start in range(0, len(payload), 16):
                yield FakeDelta([FakeFunctionDelta(name=RENDER_A2UI_TOOL_NAME, arguments=payload[start : start + 16])])

    tool = get_a2ui_tools({"model": BareRepeatsNameModel([]), "recovery": {"maxAttempts": 1}})

    envelope = await call_tool(tool)

    assert operation(envelope, "updateComponents")["components"] == VALID_COMPONENTS


@pytest.mark.asyncio
async def test_an_unkeyed_trailing_echo_keeps_the_finished_surface():
    """The same trailing echo from a provider that identifies no call."""

    class BareTrailingEchoModel(ScriptedModel):
        async def aprocess_response_stream(self, **kwargs: Any) -> AsyncIterator[FakeDelta]:
            self.calls.append(kwargs["messages"][0].content)
            yield FakeDelta(
                [
                    FakeFunctionDelta(
                        name=RENDER_A2UI_TOOL_NAME,
                        arguments=json.dumps({"surfaceId": "s", "components": VALID_COMPONENTS}),
                    )
                ]
            )
            yield FakeDelta([FakeFunctionDelta(name="search_web", arguments='{"q": "sales"}')])

    tool = get_a2ui_tools({"model": BareTrailingEchoModel([]), "recovery": {"maxAttempts": 1}})

    envelope = await call_tool(tool)

    assert operation(envelope, "updateComponents")["components"] == VALID_COMPONENTS


@pytest.mark.asyncio
async def test_only_the_first_render_call_of_a_turn_is_painted_and_committed():
    """One turn, one surface, and the same one on screen as in the result.

    Neither call's arguments may be folded into the other's, and by the time a
    second call arrives the client has already painted the first, so the first
    is the turn's: committing the second would leave the first on screen with
    nothing behind it.
    """

    class TwoCallsModel(ScriptedModel):
        async def aprocess_response_stream(self, **kwargs: Any) -> AsyncIterator[FakeDelta]:
            self.calls.append(kwargs["messages"][0].content)
            for index, surface_id in enumerate(("first", "second")):
                yield FakeDelta(
                    [
                        FakeFunctionDelta(
                            name=RENDER_A2UI_TOOL_NAME,
                            index=index,
                            id=f"call_{index}",
                            arguments=json.dumps({"surfaceId": surface_id, "components": VALID_COMPONENTS}),
                        )
                    ]
                )

    tool = get_a2ui_tools({"model": TwoCallsModel([]), "recovery": {"maxAttempts": 1}})

    envelope, pushed = await call_tool_over_the_channel(tool)

    painted = painted_calls(pushed)
    assert len(painted) == 1
    assert json.loads(painted[0]["args"])["surfaceId"] == "first"
    assert operation(envelope, "createSurface")["surfaceId"] == "first"


@pytest.mark.asyncio
async def test_each_attempt_paints_under_a_wire_id_of_its_own():
    """The retry that a shared wire id makes invisible.

    A client buffers argument fragments per tool-call id and treats a repeated
    start on one as the same call, so an attempt that reuses a rejected
    attempt's id has its arguments appended to the buffer already holding the
    rejected ones. The buffer then parses as nothing and the healed surface
    never paints, while the server records a successful generation.
    """
    model = ScriptedModel(
        [
            {"surfaceId": "sales", "components": INVALID_COMPONENTS},
            {"surfaceId": "sales", "components": VALID_COMPONENTS},
        ]
    )
    tool = get_a2ui_tools({"model": model})

    envelope, pushed = await call_tool_over_the_channel(tool)

    painted = painted_calls(pushed)
    assert len(painted) == 2
    assert len({call["call_id"] for call in painted}) == 2
    assert all(call["call_id"] and call["starts"] == 1 for call in painted)
    # Each attempt's arguments parse on their own, and the last painted
    # surface is the one committed.
    assert [json.loads(call["args"])["components"] for call in painted] == [INVALID_COMPONENTS, VALID_COMPONENTS]
    assert operation(envelope, "updateComponents")["components"] == VALID_COMPONENTS


@pytest.mark.asyncio
async def test_an_update_paints_the_surface_and_catalog_it_commits():
    """The ids an edit is committed under are the caller's and the prior
    surface's, so a stream carrying the model's own would mount the skeleton
    under an id the real surface never uses and the edit would look
    unapplied."""
    model = ScriptedModel([{"surfaceId": "invented", "components": VALID_COMPONENTS}])
    tool = get_a2ui_tools({"model": model})
    context = FakeRunContext(
        messages=[prior_surface_message("sales", catalog_id="a-catalog-of-its-own")],
        dependencies=schema_dependencies(),
    )

    envelope, pushed = await call_tool_over_the_channel(
        tool, context, intent="update", target_surface_id="sales", changes="make it red"
    )

    painted = painted_calls(pushed)
    assert len(painted) == 1
    surface = json.loads(painted[0]["args"])
    assert (surface["surfaceId"], surface["catalogId"]) == ("sales", "a-catalog-of-its-own")
    assert operation(envelope, "updateComponents")["surfaceId"] == "sales"


@pytest.mark.parametrize("named", ["", None, 7, ["s"]], ids=["empty", "null", "number", "list"])
@pytest.mark.asyncio
async def test_a_create_naming_a_surface_that_cannot_be_committed_is_retried(named):
    """A create names its own surface, and the client paints the name it was sent.

    The envelope builder commits that name only when it is a non-empty string
    and narrows anything else to the configured default, so a model that
    answers with ``""``, ``null`` or a number paints one surface and commits
    another: the skeleton the client mounted is never filled and the surface
    that was committed is never painted. The attempt is refused instead, and
    the model is told what to name.
    """
    model = ScriptedModel(
        [
            {"surfaceId": named, "components": VALID_COMPONENTS},
            {"surfaceId": "sales", "components": VALID_COMPONENTS},
        ]
    )
    tool = get_a2ui_tools({"model": model})

    envelope, pushed = await call_tool_over_the_channel(tool)

    committed = operation(envelope, "createSurface")["surfaceId"]
    assert committed == "sales"
    assert json.loads(painted_calls(pushed)[-1]["args"])["surfaceId"] == committed
    assert len(model.calls) == 2
    # Reported as a sub-agent that never called the render tool, the model has
    # nothing to correct and answers the same way again.
    assert "surfaceId" in model.calls[1]


@pytest.mark.asyncio
async def test_a_create_that_names_no_surface_at_all_still_gets_the_default():
    """Nothing was painted under a competing id, so nothing disagrees.

    A name the model never wrote leaves the client no skeleton to orphan, and
    the configured default is a renderable answer. Costing an attempt here
    would spend a retry on a surface that was already fine.
    """
    model = ScriptedModel([{"components": VALID_COMPONENTS}])
    tool = get_a2ui_tools({"model": model, "default_surface_id": "host-default"})

    envelope, pushed = await call_tool_over_the_channel(tool)

    assert operation(envelope, "createSurface")["surfaceId"] == "host-default"
    assert "surfaceId" not in json.loads(painted_calls(pushed)[-1]["args"])
    assert len(model.calls) == 1


@pytest.mark.asyncio
async def test_render_arguments_that_are_not_an_object_count_as_a_failed_attempt():
    """The shared toolkit reads the arguments as a mapping. A list reaching it
    would raise there and abort the whole run instead of costing one attempt."""

    class ListArgsModel(ScriptedModel):
        async def aprocess_response_stream(self, **kwargs: Any) -> AsyncIterator[FakeDelta]:
            self.calls.append(kwargs["messages"][0].content)
            yield FakeDelta(
                [
                    FakeFunctionDelta(
                        name=RENDER_A2UI_TOOL_NAME,
                        index=0,
                        arguments=json.dumps([{"surfaceId": "s", "components": VALID_COMPONENTS}]),
                    )
                ]
            )

    tool = get_a2ui_tools({"model": ListArgsModel([]), "recovery": {"maxAttempts": 1}})

    envelope = await call_tool(tool)

    assert envelope["code"] == "a2ui_recovery_exhausted"
    assert any("not an object" in cause for cause in envelope["subagentErrors"])


# =============================================================================
# The render turn in isolation
# =============================================================================


def host_identity(surface_id: Optional[str] = None, catalog_id: Optional[str] = None) -> A2UIRenderAttempt:
    """The identity a served run decides for one attempt before it streams."""
    return A2UIRenderAttempt.new(surface_id=surface_id, catalog_id=catalog_id)


def render_once(
    frames: List[List[Any]],
    attempt: Optional[A2UIRenderAttempt] = None,
    messages: Optional[List[Any]] = None,
) -> Any:
    """Run one render turn over scripted frames, collecting what it pushed.

    Arguments the turn cannot use are raised rather than returned, and what it
    painted before that is part of what has to be asserted, so the error comes
    back as the outcome instead of ending the test.
    """

    class FrameModel:
        assistant_message_role = "assistant"

        def __init__(self) -> None:
            self.seen_messages: List[Any] = []

        async def aprocess_response_stream(self, **kwargs: Any) -> AsyncIterator[FakeDelta]:
            self.seen_messages = list(kwargs["messages"])
            for frame in frames:
                yield FakeDelta(frame)

    model = FrameModel()
    pushed: List[Dict[str, Any]] = []
    try:
        outcome: Any = asyncio.run(
            stream_render_subagent(
                model,
                "RENDER PROMPT",
                messages or [],
                None,
                push=pushed.append,
                attempt=attempt,
            )
        )
    except A2UIRenderArgumentsError as err:
        outcome = err
    return model, outcome, pushed


def emitted_args(pushed: List[Dict[str, Any]]) -> str:
    """The argument stream a progressively painting client would have seen."""
    return "".join(event["delta"] for event in pushed if event["kind"] == "args")


def render_frame(arguments: str, **kwargs: Any) -> List[Any]:
    return [FakeFunctionDelta(name=RENDER_A2UI_TOOL_NAME, arguments=arguments, index=0, **kwargs)]


def continuation_frame(arguments: str) -> List[Any]:
    return [FakeFunctionDelta(arguments=arguments, index=0)]


def test_the_host_ids_lead_the_argument_stream():
    """A client mounts the surface as soon as it can read which one it is, so
    the host's ids have to reach the stream before the model's own members."""
    _, _, pushed = render_once(
        [render_frame('{"components": []}')],
        attempt=host_identity(surface_id="sales", catalog_id="cat"),
    )

    first = next(event["delta"] for event in pushed if event["kind"] == "args")
    assert first.startswith('{"surfaceId": "sales", "catalogId": "cat"')


def test_an_id_the_model_wrote_itself_never_wins_the_surface_back():
    """Two identical keys leave a parser holding the last one.

    On an update the surface the caller named is the one committed, so a
    member the model wrote under the same name has to be gone from the stream
    rather than merely preceded by the host's: left in, it would take the
    painted surface back at the end of the stream and orphan the skeleton the
    client had already mounted.
    """
    payload = json.dumps(
        {"surfaceId": "invented", "catalogId": "invented-too", "components": VALID_COMPONENTS},
    )

    _, args, pushed = render_once([render_frame(payload)], attempt=host_identity("sales", "cat"))

    emitted = json.loads(emitted_args(pushed))
    assert (emitted["surfaceId"], emitted["catalogId"]) == ("sales", "cat")
    assert emitted["components"] == VALID_COMPONENTS
    # What validation reads is still exactly what the model wrote.
    assert args["surfaceId"] == "invented"


def test_a_create_leaves_the_surface_id_to_the_model():
    """Only an update has a surface to impose. Imposing one on a create would
    rename every surface the model makes, and the envelope keeps the model's."""
    _, _, pushed = render_once([render_frame('{"surfaceId": "s"}')], attempt=host_identity(catalog_id="cat"))

    assert json.loads(emitted_args(pushed)) == {"catalogId": "cat", "surfaceId": "s"}


def test_an_empty_argument_object_is_not_a_usable_surface():
    _, args, pushed = render_once([render_frame("{}")], attempt=host_identity(catalog_id="cat"))

    assert json.loads(emitted_args(pushed)) == {"catalogId": "cat"}
    assert isinstance(args, A2UIRenderArgumentsError)
    assert "empty object" in str(args)


def test_the_host_ids_survive_a_brace_only_first_fragment():
    _, _, pushed = render_once(
        [render_frame("{"), continuation_frame('"surfaceId": "s"}')],
        attempt=host_identity(catalog_id="cat"),
    )

    assert json.loads(emitted_args(pushed)) == {"catalogId": "cat", "surfaceId": "s"}


def test_the_host_ids_survive_an_object_closed_in_a_later_fragment():
    _, _, pushed = render_once(
        [render_frame("{"), continuation_frame("}")],
        attempt=host_identity(catalog_id="cat"),
    )

    assert json.loads(emitted_args(pushed)) == {"catalogId": "cat"}


def test_leading_whitespace_does_not_displace_the_host_ids():
    _, _, pushed = render_once(
        [render_frame("  "), continuation_frame('{"surfaceId": "s"}')],
        attempt=host_identity(catalog_id="cat"),
    )

    assert json.loads(emitted_args(pushed)) == {"catalogId": "cat", "surfaceId": "s"}


@pytest.mark.parametrize("width", [1, 3, 7, 4096], ids=["char", "tiny", "small", "whole"])
def test_a_member_split_across_fragments_survives_the_rewrite(width):
    """The rewrite reads the stream a character at a time, and a provider
    breaks it wherever it likes: mid-key, mid-string, and inside a nested
    object whose braces and quotes are not the object's own."""
    text = 'a } {" b'
    payload = {"surfaceId": "invented", "components": [{"id": "root", "component": "Text", "text": text}]}
    raw = json.dumps(payload)
    frames = [render_frame(raw[:width])] + [
        continuation_frame(raw[start : start + width]) for start in range(width, len(raw), width)
    ]

    _, args, pushed = render_once(frames, attempt=host_identity("sales", "cat"))

    assert json.loads(emitted_args(pushed)) == {
        "surfaceId": "sales",
        "catalogId": "cat",
        "components": payload["components"],
    }
    assert args == payload


def test_the_host_ids_are_never_written_into_a_nested_object():
    """Arguments that are not an object have no place to carry an id, so the
    stream must go out exactly as the model wrote it."""
    fragments = ["[", '{"surfaceId": "s"}', "]"]
    frames = [render_frame(fragments[0])] + [continuation_frame(fragment) for fragment in fragments[1:]]

    _, args, pushed = render_once(frames, attempt=host_identity("sales", "cat"))

    assert emitted_args(pushed) == "".join(fragments)
    assert isinstance(args, A2UIRenderArgumentsError)
    assert "not an object" in str(args)


def test_the_arguments_kept_for_validation_are_never_rewritten():
    payload = {"surfaceId": "s", "components": VALID_COMPONENTS}
    _, args, pushed = render_once([render_frame(json.dumps(payload))], attempt=host_identity(catalog_id="cat"))

    assert args == payload
    assert json.loads(emitted_args(pushed))["catalogId"] == "cat"


def test_a_stream_that_owns_no_ids_is_passed_through_untouched():
    """Nothing to impose means nothing to rewrite: a caller with no ids of its
    own gets the model's bytes, separators and whitespace included."""
    raw = '{ "surfaceId" : "s" ,  "components" : [] }'

    _, _, pushed = render_once([render_frame(raw)])

    assert emitted_args(pushed) == raw


#: One row per way out of the argument rewrite: what the model wrote, and the
#: object a progressively painting client is left holding. A client reads these
#: fragments with an incremental JSON parser, so an exit that omits the comma
#: or the colon it swallowed does not paint a surface late, it paints none at
#: all, and the rewrite exists to keep invalid JSON off the wire rather than to
#: make new ones.
REWRITE_EXITS: Dict[str, Any] = {
    "the-object-ends": ('{"components": []}', {"catalogId": "cat", "components": []}),
    "a-host-owned-member-ends-it": (
        '{"components": [], "catalogId": "guessed"}',
        {"catalogId": "cat", "components": []},
    ),
    "nothing-an-object-may-contain": ('{"components": [], 5}', {"catalogId": "cat", "components": []}),
    "a-key-with-no-colon": ('{"surfaceId" "s"}', {"catalogId": "cat"}),
    "a-key-with-no-colon-after-a-member": (
        '{"components": [], "surfaceId" "s"}',
        {"catalogId": "cat", "components": []},
    ),
    "bytes-after-the-object": ('{"components": []} and then some', {"catalogId": "cat", "components": []}),
    "arguments-that-are-not-an-object": ('[{"surfaceId": "s"}]', [{"surfaceId": "s"}]),
    "arguments-that-are-a-bare-string": ('"a surface, honest"', "a surface, honest"),
}


@pytest.mark.parametrize("exit_name", list(REWRITE_EXITS), ids=list(REWRITE_EXITS))
def test_every_way_out_of_the_rewrite_leaves_the_client_parseable_json(exit_name):
    raw, expected = REWRITE_EXITS[exit_name]

    _, _, pushed = render_once([render_frame(raw)], attempt=host_identity(catalog_id="cat"))

    assert json.loads(emitted_args(pushed)) == expected


@pytest.mark.parametrize("exit_name", list(REWRITE_EXITS), ids=list(REWRITE_EXITS))
def test_the_rewrite_leaves_parseable_json_however_the_fragments_fall(exit_name):
    """The same exits, reached a character at a time.

    The rewrite keeps its state across fragments, so a provider that breaks
    the arguments mid-key or mid-string must not reach a different exit from
    one that hands them over whole.
    """
    raw, expected = REWRITE_EXITS[exit_name]
    frames = [render_frame(raw[:1])] + [continuation_frame(char) for char in raw[1:]]

    _, _, pushed = render_once(frames, attempt=host_identity(catalog_id="cat"))

    assert json.loads(emitted_args(pushed)) == expected


def test_arguments_that_are_not_valid_json_say_what_went_wrong():
    _, args, _ = render_once([render_frame('{"surfaceId": "s", "comp')])

    assert isinstance(args, A2UIRenderArgumentsError)
    assert "not valid JSON" in str(args)


def test_a_turn_with_no_render_call_at_all_returns_none():
    _, args, _ = render_once([[FakeFunctionDelta(name="search_web", index=0, arguments="{}")]])

    assert args is None


def test_the_emitted_call_is_always_terminated():
    _, _, pushed = render_once([render_frame('{"surfaceId": "s"}')])

    assert [event["kind"] for event in pushed] == ["start", "args", "end"]
    # An id is mandatory on every tool-call event, so a fragment carrying an
    # empty one is dropped whole and the surface never paints. This frame has
    # no id of its own, which is the case a minted identity exists for.
    assert {event["tool_call_id"] for event in pushed} == {pushed[0]["tool_call_id"]}
    assert pushed[0]["tool_call_id"]


def test_every_event_is_emitted_under_the_attempts_own_id():
    """Not the provider's, which it reuses across attempts: the client buffers
    argument fragments per wire id, so a reused id holds two attempts at once."""
    attempt = host_identity()
    frames = [render_frame('{"surfaceId": "s"}', id="provider-1")]

    _, _, pushed = render_once(frames, attempt=attempt)

    assert {event["tool_call_id"] for event in pushed} == {attempt.call_id}
    assert attempt.call_id != "provider-1"


# =============================================================================
# One render call, as each provider spells it out
# =============================================================================

RENDER_ARGS = {"surfaceId": "s", "components": VALID_COMPONENTS}
RENDER_PAYLOAD = json.dumps(RENDER_ARGS)
FIRST_HALF = RENDER_PAYLOAD[: len(RENDER_PAYLOAD) // 2]
SECOND_HALF = RENDER_PAYLOAD[len(RENDER_PAYLOAD) // 2 :]

#: One row per provider shape: the frames the model streams, the arguments the
#: turn must return, and the fragment sequence a progressively painting client
#: must see. The second half is what nothing observed before: the state of the
#: call in progress is five mutable locals with no closed transition set, and
#: every guard over them is otherwise assertable only through the committed
#: envelope.
FRAME_SEQUENCES: Dict[str, Any] = {
    "openai-index-only": (
        [
            [FakeFunctionDelta(name=RENDER_A2UI_TOOL_NAME, index=0, arguments=FIRST_HALF)],
            [FakeFunctionDelta(index=0, arguments=SECOND_HALF)],
        ],
        RENDER_ARGS,
        [("start", 0), ("args", 0), ("args", 0), ("end", 0)],
    ),
    "id-and-index-on-every-frame": (
        [
            [FakeFunctionDelta(name=RENDER_A2UI_TOOL_NAME, index=0, id="c1", arguments=FIRST_HALF)],
            [FakeFunctionDelta(index=0, id="c1", arguments=SECOND_HALF)],
        ],
        RENDER_ARGS,
        [("start", 0), ("args", 0), ("args", 0), ("end", 0)],
    ),
    "anthropic-single-dict": (
        [[{"id": "c1", "type": "function", "function": {"name": RENDER_A2UI_TOOL_NAME, "arguments": RENDER_PAYLOAD}}]],
        RENDER_ARGS,
        [("start", 0), ("args", 0), ("end", 0)],
    ),
    "gemini-identifies-no-call": (
        [[{"type": "function", "function": {"name": RENDER_A2UI_TOOL_NAME, "arguments": RENDER_PAYLOAD}}]],
        RENDER_ARGS,
        [("start", 0), ("args", 0), ("end", 0)],
    ),
    "ollama-repeats-the-name-unkeyed": (
        [
            [FakeFunctionDelta(name=RENDER_A2UI_TOOL_NAME, arguments=FIRST_HALF)],
            [FakeFunctionDelta(name=RENDER_A2UI_TOOL_NAME, arguments=SECOND_HALF)],
        ],
        RENDER_ARGS,
        [("start", 0), ("args", 0), ("args", 0), ("end", 0)],
    ),
    "unkeyed-continuation-fragments": (
        [
            [FakeFunctionDelta(name=RENDER_A2UI_TOOL_NAME, arguments=FIRST_HALF)],
            [FakeFunctionDelta(arguments=SECOND_HALF)],
        ],
        RENDER_ARGS,
        [("start", 0), ("args", 0), ("args", 0), ("end", 0)],
    ),
    "only-the-opening-frame-is-keyed": (
        [
            [FakeFunctionDelta(name=RENDER_A2UI_TOOL_NAME, index=0, id="c1", arguments=FIRST_HALF)],
            [FakeFunctionDelta(arguments=SECOND_HALF)],
        ],
        RENDER_ARGS,
        [("start", 0), ("args", 0), ("args", 0), ("end", 0)],
    ),
    # The mirror image of the OpenAI shape: the id is stamped on the opening
    # frame and the index on the continuations. Keyed by a fixed preference for
    # one dimension, every continuation of one of the two families reads as a
    # different call and the whole surface is dropped.
    "only-continuations-are-keyed": (
        [
            [FakeFunctionDelta(name=RENDER_A2UI_TOOL_NAME, id="c1", arguments=FIRST_HALF)],
            [FakeFunctionDelta(index=0, arguments=SECOND_HALF)],
        ],
        RENDER_ARGS,
        [("start", 0), ("args", 0), ("args", 0), ("end", 0)],
    ),
    "another-call-s-fragments-after-an-id-keyed-opener": (
        [
            [FakeFunctionDelta(name=RENDER_A2UI_TOOL_NAME, id="c1", arguments=FIRST_HALF)],
            [FakeFunctionDelta(index=0, arguments=SECOND_HALF)],
            [FakeFunctionDelta(index=1, arguments='{"query": "sales"}')],
        ],
        RENDER_ARGS,
        [("start", 0), ("args", 0), ("args", 0), ("end", 0)],
    ),
    "a-fragment-for-another-id-after-an-id-keyed-opener": (
        [
            [FakeFunctionDelta(name=RENDER_A2UI_TOOL_NAME, id="c1", arguments=RENDER_PAYLOAD)],
            [FakeFunctionDelta(id="c2", arguments='{"query": "sales"}')],
        ],
        RENDER_ARGS,
        [("start", 0), ("args", 0), ("end", 0)],
    ),
    "the-tool-name-arrives-in-fragments": (
        [
            [FakeFunctionDelta(name="render", index=0, arguments="")],
            [FakeFunctionDelta(name="_a2ui", index=0, arguments="")],
            [FakeFunctionDelta(index=0, arguments=RENDER_PAYLOAD)],
        ],
        RENDER_ARGS,
        [("start", 0), ("args", 0), ("end", 0)],
    ),
    "the-tool-name-arrives-in-fragments-keyed-two-ways": (
        [
            [FakeFunctionDelta(name="render", id="c1", arguments="")],
            [FakeFunctionDelta(name="_a2ui", index=0, arguments="")],
            [FakeFunctionDelta(index=0, arguments=RENDER_PAYLOAD)],
        ],
        RENDER_ARGS,
        [("start", 0), ("args", 0), ("end", 0)],
    ),
    "a-foreign-name-that-begins-like-the-render-tool-s": (
        [
            [FakeFunctionDelta(name="render", index=0, arguments="{}")],
            [FakeFunctionDelta(name=RENDER_A2UI_TOOL_NAME, index=0, arguments=RENDER_PAYLOAD)],
        ],
        RENDER_ARGS,
        [("start", 0), ("args", 0), ("end", 0)],
    ),
    "another-tool-takes-the-live-call-s-place": (
        [
            [FakeFunctionDelta(name=RENDER_A2UI_TOOL_NAME, index=0, arguments=FIRST_HALF)],
            [FakeFunctionDelta(name="search_web", index=0, arguments="{}")],
            [FakeFunctionDelta(index=0, arguments=SECOND_HALF)],
        ],
        # The render call is over, so its arguments are truncated and cost an
        # attempt. What must not happen is a fragment after its end.
        A2UIRenderArgumentsError,
        [("start", 0), ("args", 0), ("end", 0)],
    ),
    "an-unkeyed-fragment-arrives-after-the-call-closed": (
        [
            [FakeFunctionDelta(name=RENDER_A2UI_TOOL_NAME, index=0, arguments=FIRST_HALF)],
            [FakeFunctionDelta(name="search_web", index=0, arguments="{}")],
            [FakeFunctionDelta(arguments=SECOND_HALF)],
        ],
        # The tail of the committed surface, arriving on a frame that names no
        # call. Dropped either way, but an operator whose surfaces truncate is
        # owed the reason.
        A2UIRenderArgumentsError,
        [("start", 0), ("args", 0), ("end", 0)],
    ),
    "another-tool-opens-beside-the-live-call": (
        [
            [FakeFunctionDelta(name=RENDER_A2UI_TOOL_NAME, index=0, arguments=FIRST_HALF)],
            [FakeFunctionDelta(name="search_web", index=1, arguments="{}")],
            [FakeFunctionDelta(index=0, arguments=SECOND_HALF)],
        ],
        RENDER_ARGS,
        [("start", 0), ("args", 0), ("args", 0), ("end", 0)],
    ),
    "another-tool-echoed-with-nothing-to-key-on": (
        [
            [FakeFunctionDelta(name=RENDER_A2UI_TOOL_NAME, arguments=FIRST_HALF)],
            [FakeFunctionDelta(name="search_web", arguments="{}")],
            [FakeFunctionDelta(arguments=SECOND_HALF)],
        ],
        RENDER_ARGS,
        [("start", 0), ("args", 0), ("args", 0), ("end", 0)],
    ),
    # A turn commits one surface, and the client has already painted the first
    # call by the time a second arrives, so the first is the turn's and the
    # rest are dropped: painting both would leave one on screen with nothing
    # behind it.
    "two-render-calls-keyed-by-index": (
        [
            [FakeFunctionDelta(name=RENDER_A2UI_TOOL_NAME, index=0, arguments='{"surfaceId": "first"}')],
            [FakeFunctionDelta(name=RENDER_A2UI_TOOL_NAME, index=1, arguments=RENDER_PAYLOAD)],
        ],
        {"surfaceId": "first"},
        [("start", 0), ("args", 0), ("end", 0)],
    ),
    "two-render-calls-keyed-by-id": (
        [
            [FakeFunctionDelta(name=RENDER_A2UI_TOOL_NAME, id="c1", arguments='{"surfaceId": "first"}')],
            [FakeFunctionDelta(name=RENDER_A2UI_TOOL_NAME, id="c2", arguments=RENDER_PAYLOAD)],
        ],
        {"surfaceId": "first"},
        [("start", 0), ("args", 0), ("end", 0)],
    ),
    "a-render-call-that-reopens-after-its-end": (
        [
            [FakeFunctionDelta(name=RENDER_A2UI_TOOL_NAME, index=0, arguments=FIRST_HALF)],
            [FakeFunctionDelta(name="search_web", index=0, arguments="{}")],
            [FakeFunctionDelta(name=RENDER_A2UI_TOOL_NAME, index=1, arguments=RENDER_PAYLOAD)],
        ],
        A2UIRenderArgumentsError,
        [("start", 0), ("args", 0), ("end", 0)],
    ),
    "a-render-call-with-no-arguments": (
        [[FakeFunctionDelta(name=RENDER_A2UI_TOOL_NAME, index=0, arguments="")]],
        A2UIRenderArgumentsError,
        [("start", 0), ("end", 0)],
    ),
    "no-render-call-at-all": (
        [[FakeFunctionDelta(name="search_web", index=0, arguments="{}")]],
        None,
        [],
    ),
    "another-call-s-continuation-fragments": (
        [
            [FakeFunctionDelta(name=RENDER_A2UI_TOOL_NAME, index=0, arguments=RENDER_PAYLOAD)],
            [FakeFunctionDelta(index=1, arguments='{"query": "sales"}')],
        ],
        RENDER_ARGS,
        [("start", 0), ("args", 0), ("end", 0)],
    ),
}


def pushed_shape(pushed: List[Dict[str, Any]]) -> List[Any]:
    """Each fragment's kind and which call it belongs to.

    Calls are numbered by first appearance rather than by id, because a
    provider that identifies no call has one synthesized for it and the id is
    not predictable.
    """
    calls: List[str] = []
    for event in pushed:
        if event["tool_call_id"] not in calls:
            calls.append(event["tool_call_id"])
    return [(event["kind"], calls.index(event["tool_call_id"])) for event in pushed]


@pytest.mark.parametrize("shape", list(FRAME_SEQUENCES), ids=list(FRAME_SEQUENCES))
def test_the_fragment_sequence_each_provider_shape_produces(shape):
    """Both halves of one render turn: what it returns, and what it emitted.

    A client paints from the emitted fragments alone, so a guard in this loop
    that only the committed envelope observes can be deleted with the suite
    green. Each row asserts the sequence too, and every fragment's id, since a
    fragment with an empty id is dropped before it becomes an event.
    """
    frames, expected_args, expected_shape = FRAME_SEQUENCES[shape]

    _, args, pushed = render_once(frames)

    assert all(event["tool_call_id"] for event in pushed)
    if expected_args is A2UIRenderArgumentsError:
        assert isinstance(args, A2UIRenderArgumentsError)
    else:
        assert args == expected_args
    assert pushed_shape(pushed) == expected_shape


@pytest.fixture
def diagnostics(monkeypatch):
    """Every diagnostic this module emits during the test, with its level."""
    collected: List[Tuple[str, str]] = []

    def recorder(level: str):
        def record(msg: Any, *args: Any, **kwargs: Any) -> None:
            collected.append((level, str(msg)))

        return record

    for level in ("log_debug", "log_warning", "log_error"):
        monkeypatch.setattr(a2ui_module, level, recorder(level))
    return collected


#: One row per branch of the render loop that declines to do what the stream
#: asked: which provider shape takes it, what it has to say for itself, and
#: how loudly. Lost arguments are a warning because the committed surface is
#: not what the model wrote; the rest are ordinary provider behaviour.
SILENT_BRANCHES: Dict[str, Any] = {
    "the-tool-name-arrives-in-fragments": ("log_debug", "tool name in fragments"),
    "another-tool-echoed-with-nothing-to-key-on": ("log_debug", "not the render tool"),
    "another-call-s-continuation-fragments": ("log_debug", "not the render call"),
    "no-render-call-at-all": ("log_debug", "produced no render call"),
    "two-render-calls-keyed-by-index": ("log_warning", "more than one render call"),
    "another-tool-takes-the-live-call-s-place": ("log_warning", "may therefore be truncated"),
    # The same truncation, on a frame that names no call: a provider keyed only
    # on its opening frame loses the tail of its surface exactly as quietly.
    "an-unkeyed-fragment-arrives-after-the-call-closed": ("log_warning", "may therefore be truncated"),
}


@pytest.mark.parametrize("shape", list(SILENT_BRANCHES), ids=list(SILENT_BRANCHES))
def test_a_branch_that_declines_says_so_exactly_once(shape, diagnostics):
    """A turn that quietly drops what it was sent leaves nobody anything to read.

    Every one of these ends with a surface the caller did not ask for, or with
    an attempt reported to the model as a sub-agent that never called the
    render tool, and none of them said which.
    """
    level, phrase = SILENT_BRANCHES[shape]
    frames = FRAME_SEQUENCES[shape][0]

    render_once(frames)

    said = [record for record in diagnostics if phrase in record[1]]
    assert len(said) == 1, f"expected one {phrase!r} diagnostic, got {said}"
    assert said[0][0] == level


def test_the_same_branch_taken_by_every_fragment_is_reported_once(diagnostics):
    """A provider sends hundreds of fragments and each can take the same turn."""
    frames = [[FakeFunctionDelta(name=RENDER_A2UI_TOOL_NAME, index=0, arguments=RENDER_PAYLOAD)]]
    frames += [[FakeFunctionDelta(index=1, arguments="x")] for _ in range(50)]

    render_once(frames)

    assert len([record for record in diagnostics if "not the render call" in record[1]]) == 1


def test_the_host_system_prompt_does_not_reach_the_subagent():
    """Two system messages set the render prompt against the host persona, and
    the persona tends to win: the subagent answers in prose."""
    history = [
        {"role": "system", "content": "You are a SALES ANALYST. Always answer in prose."},
        {"role": "developer", "content": "Never call tools."},
        {"role": "user", "content": "show me a card"},
    ]

    model, _, _ = render_once([render_frame('{"surfaceId": "s"}')], messages=history)

    roles = [
        message.get("role") if isinstance(message, dict) else getattr(message, "role", None)
        for message in model.seen_messages
    ]
    assert roles == ["system", "user"]
    assert model.seen_messages[0].content == "RENDER PROMPT"


# =============================================================================
# Helpers
# =============================================================================


def test_state_is_rebuilt_from_forwarded_context():
    state = agui_state_from_dependencies(schema_dependencies())

    assert json.loads(state["ag-ui"]["a2ui_schema"])["catalogId"] == CATALOG_ID
    assert state["ag-ui"]["context"] == [{"description": "User preferences", "value": {"currency": "USD"}}]


def test_state_without_any_context():
    assert agui_state_from_dependencies(None) == {"ag-ui": {"context": []}}


def test_a_string_schema_is_left_alone():
    raw = '{"catalogId": "already-json"}'
    state = agui_state_from_dependencies({A2UI_SCHEMA_CONTEXT_DESCRIPTION: raw})

    assert state["ag-ui"]["a2ui_schema"] == raw


def test_forwarded_context_reaches_the_toolkit_as_plain_entries():
    """The served route forwards context as request models, not as dicts.

    The shared toolkit scans these entries for the catalog the client named and
    skips anything that is not a dict, so left as models the catalog it finds
    is none and the surface is bound to the basic catalog the client never
    registered.
    """
    from ag_ui.core import Context
    from ag_ui_a2ui_toolkit import resolve_a2ui_catalog

    entry = Context(description="A2UI catalog and components", value=f"- {CATALOG_ID}\n")

    state = a2ui_module.build_agui_state(None, [entry])

    assert state["ag-ui"]["context"] == [{"description": entry.description, "value": entry.value}]
    assert resolve_a2ui_catalog(state) == (entry.value, CATALOG_ID)


def test_an_injected_run_leaves_the_toolkit_the_same_readable_entries():
    """The run this injects into rebuilds its state context from the plan.

    That assignment is the last word on what the toolkit reads, so a run that
    generates would otherwise be the one run whose entries it cannot read.
    """
    pytest.importorskip("openai")
    from ag_ui.core import RunAgentInput
    from ag_ui_a2ui_toolkit import resolve_a2ui_catalog

    from agno.models.openai import OpenAIChat

    entry = {"description": "A2UI catalog and components", "value": f"- {CATALOG_ID}\n"}
    run_input = RunAgentInput.model_validate(
        {
            "threadId": "t",
            "runId": "r",
            "state": None,
            "messages": [{"id": "m1", "role": "user", "content": "show me a card"}],
            "tools": [],
            "context": [entry],
            "forwardedProps": {"injectA2UITool": True},
        }
    )

    plan = a2ui_module.prepare_a2ui_run(
        entity=Agent(id="a", name="A", model=OpenAIChat(id="gpt-x", api_key="not-used")),
        run_input=run_input,
    )

    assert plan["tool"] is not None
    assert resolve_a2ui_catalog(plan["run"].state) == (entry["value"], CATALOG_ID)


def test_the_in_flight_generation_call_is_stripped():
    history = [
        {"role": "user", "content": "make a card"},
        {"role": "assistant", "content": None, "tool_calls": [{"function": {"name": GENERATE_A2UI_TOOL_NAME}}]},
    ]

    assert strip_in_flight_tool_call(history, GENERATE_A2UI_TOOL_NAME) == history[:1]


def test_a_trailing_user_turn_is_kept():
    history = [{"role": "user", "content": "make a card"}]

    assert strip_in_flight_tool_call(history, GENERATE_A2UI_TOOL_NAME) == history


def test_a_trailing_tool_result_carrying_the_generation_call_is_kept():
    """Only an assistant turn can be the call in progress.

    A trailing ``tool`` or ``user`` message naming the generation tool is a
    result, not an unanswered call, and dropping it would take the surface the
    model is being asked to edit out of the history it edits from.
    """
    history = [
        {"role": "user", "content": "make a card"},
        {
            "role": "tool",
            "content": "{}",
            "tool_calls": [{"function": {"name": GENERATE_A2UI_TOOL_NAME}}],
        },
    ]

    assert strip_in_flight_tool_call(history, GENERATE_A2UI_TOOL_NAME) == history


def test_another_agents_trailing_tool_call_is_kept():
    history = [
        {"role": "assistant", "content": None, "tool_calls": [{"function": {"name": "search_web"}}]},
    ]

    assert strip_in_flight_tool_call(history, GENERATE_A2UI_TOOL_NAME) == history


def test_empty_history():
    assert strip_in_flight_tool_call([], GENERATE_A2UI_TOOL_NAME) == []


# =============================================================================
# Over the wire
# =============================================================================


def parse_sse_events(content: str) -> List[Dict[str, Any]]:
    """Every ``data:`` frame the server sent, parsed.

    Nothing is skipped: a frame that is not valid JSON is a broken event, and
    swallowing it would take a RUN_ERROR or a truncated tool result out of the
    stream before the assertions below ever counted it.
    """
    events = []
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("data:"):
            payload = line[5:].strip()
            try:
                events.append(json.loads(payload))
            except json.JSONDecodeError as err:
                raise AssertionError(f"the server sent a data frame that is not valid JSON: {payload!r}") from err
    return events


def test_the_generated_surface_reaches_the_wire():
    """The envelope must arrive as the tool result, verbatim, or the client
    renderer never sees a surface."""
    pytest.importorskip("openai")
    from openai.types.chat import ChatCompletionChunk

    from agno.models.openai import OpenAIChat

    turns = {"n": 0}

    def chunk(delta):
        return ChatCompletionChunk.model_validate(
            {
                "id": "c",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "m",
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
            }
        )

    class PlannerModel(OpenAIChat):
        async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:  # type: ignore[override]
            turns["n"] += 1
            if turns["n"] == 1:
                yield self._parse_provider_response_delta(
                    chunk(
                        {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "outer",
                                    "type": "function",
                                    "function": {"name": GENERATE_A2UI_TOOL_NAME, "arguments": "{}"},
                                }
                            ]
                        }
                    )
                )
            elif turns["n"] == 2:
                # The render subagent turn.
                yield self._parse_provider_response_delta(
                    chunk(
                        {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "inner",
                                    "type": "function",
                                    "function": {
                                        "name": RENDER_A2UI_TOOL_NAME,
                                        "arguments": json.dumps({"surfaceId": "sales", "components": VALID_COMPONENTS}),
                                    },
                                }
                            ]
                        }
                    )
                )
            else:
                yield self._parse_provider_response_delta(chunk({"content": "Rendered."}))

    model = PlannerModel(id="m", api_key="x")
    agent = Agent(id="a2ui-agent", name="A2UI Agent", model=model, tools=[get_a2ui_tools({"model": model})])
    app = AgentOS(id="a2ui-os", agents=[agent], interfaces=[AGUI(agent=agent)]).get_app()

    body = {
        "threadId": "thread-1",
        "runId": "run-1",
        "state": None,
        "messages": [{"id": "m1", "role": "user", "content": "show me a sales card"}],
        "tools": [],
        "context": [
            {
                "description": A2UI_SCHEMA_CONTEXT_DESCRIPTION,
                "value": json.dumps(
                    forwarded_catalog(Column=catalog_component("Column"), Text=catalog_component("Text", "text"))
                ),
            }
        ],
        "forwardedProps": {},
    }

    with TestClient(app) as client:
        response = client.post("/agui", json=body)

    assert response.status_code == 200
    events = parse_sse_events(response.text)
    assert "RUN_ERROR" not in [event.get("type") for event in events]

    results = [event for event in events if event.get("type") == "TOOL_CALL_RESULT"]
    assert len(results) == 1
    envelope = json.loads(results[0]["content"])
    assert operation(envelope, "createSurface") == {"surfaceId": "sales", "catalogId": CATALOG_ID}
    assert operation(envelope, "updateComponents")["components"] == VALID_COMPONENTS

    starts = [event["toolCallName"] for event in events if event.get("type") == "TOOL_CALL_START"]
    assert starts == [GENERATE_A2UI_TOOL_NAME, RENDER_A2UI_TOOL_NAME]
