"""Giving an agent the A2UI generation tool for a single request.

A client that can render A2UI asks for generation per run. The interface adds
the tool for that run only, because the agent is shared across requests and the
tool is bound to one. Asking is opt-in and refusing is always honoured.
"""

import asyncio
import json
import logging
import sys
import types
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")
pytest.importorskip("ag_ui_a2ui_toolkit", reason="ag_ui_a2ui_toolkit not installed")

from ag_ui.core import EventType, RunAgentInput, RunFinishedEvent, RunStartedEvent  # noqa: E402
from ag_ui_a2ui_toolkit import (  # noqa: E402
    A2UI_SCHEMA_CONTEXT_DESCRIPTION,
    BASIC_CATALOG_ID,
    GENERATE_A2UI_TOOL_NAME,
)

from agno.agent import Agent  # noqa: E402
from agno.agent.remote import RemoteAgent  # noqa: E402
from agno.models.response import ToolExecution  # noqa: E402
from agno.os.app import AgentOS  # noqa: E402
from agno.os.interfaces.agui import AGUI  # noqa: E402
from agno.os.interfaces.agui import a2ui as a2ui_module  # noqa: E402
from agno.os.interfaces.agui.a2ui import (  # noqa: E402
    RENDER_A2UI_TOOL_NAME,
    A2UIConfig,
    get_a2ui_tools,
    prepare_a2ui_run,
    render_guide_description,
)
from agno.os.interfaces.agui.a2ui_stream import (  # noqa: E402
    ToolPresence,
    current_a2ui_run,
    resolve_entity_tools,
)
from agno.os.interfaces.agui.router import run_entity  # noqa: E402
from agno.run.agent import RunContentEvent, ToolCallStartedEvent  # noqa: E402
from agno.team import Team  # noqa: E402
from agno.team.remote import RemoteTeam  # noqa: E402
from agno.tools.function import Function  # noqa: E402
from agno.tools.toolkit import Toolkit  # noqa: E402
from agno.utils import log as agno_log  # noqa: E402

CATALOG_ID = "declarative-gen-ui-catalog"

COMPONENTS = [
    {"id": "root", "component": "Column", "children": ["title"]},
    {"id": "title", "component": "Text", "text": "Quarterly sales"},
]

SCHEMA_ENTRY = {
    "description": A2UI_SCHEMA_CONTEXT_DESCRIPTION,
    "value": json.dumps({"catalogId": CATALOG_ID, "components": [{"name": "Column"}, {"name": "Text"}]}),
}


def a_model() -> Any:
    """A real model instance; these tests never let it reach the network."""
    pytest.importorskip("openai")
    from agno.models.openai import OpenAIChat

    return OpenAIChat(id="gpt-x", api_key="not-used")


def run_input(
    *,
    forwarded_props: Optional[Dict[str, Any]] = None,
    context: Optional[List[Dict[str, Any]]] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    messages: Optional[List[Dict[str, Any]]] = None,
) -> RunAgentInput:
    return RunAgentInput.model_validate(
        {
            "threadId": "thread-1",
            "runId": "run-1",
            "state": None,
            "messages": messages or [{"id": "m1", "role": "user", "content": "show me a card"}],
            "tools": tools or [],
            "context": context if context is not None else [SCHEMA_ENTRY],
            "forwardedProps": forwarded_props or {},
        }
    )


def agent_with(*tools: Any, model: Any = None) -> Agent:
    return Agent(id="a", name="A", model=model if model is not None else a_model(), tools=list(tools) or None)


def a_rendering_model() -> Any:
    """A model whose single turn is one complete render call.

    Enough to run a generation tool's entrypoint offline, without the recovery
    loop needing a second attempt.
    """
    pytest.importorskip("openai")
    from agno.models.openai import OpenAIChat

    payload = json.dumps({"surfaceId": "sales", "components": COMPONENTS})

    class RenderingModel(OpenAIChat):
        async def aprocess_response_stream(self, **kwargs: Any) -> AsyncIterator[Any]:  # type: ignore[override]
            function = type("Fn", (), {"name": RENDER_A2UI_TOOL_NAME, "arguments": payload})()
            entry = type("Entry", (), {"function": function, "index": 0, "id": "inner"})()
            yield type("Delta", (), {"tool_calls": [entry]})()

    return RenderingModel(id="m", api_key="not-used")


def created_surface(envelope: Dict[str, Any]) -> Dict[str, Any]:
    return next(entry["createSurface"] for entry in envelope["a2ui_operations"] if "createSurface" in entry)


def levels_logging(caplog: Any, needle: str) -> set:
    """The levels the records mentioning ``needle`` were logged at.

    A substring match on ``caplog.text`` says a line was emitted but not how
    loudly, and the level is part of what the cookbook README promises an
    operator. Pinning it is what keeps the two from drifting apart unnoticed a
    third time.
    """
    return {record.levelname for record in caplog.records if needle in record.getMessage()}


#: Nothing listens there, so any attempt to reach the remote deployment fails
#: rather than being quietly served.
UNREACHABLE = "http://127.0.0.1:1"


# =============================================================================
# Whether the tool is added at all
# =============================================================================


def test_generation_is_off_unless_asked_for():
    plan = prepare_a2ui_run(entity=agent_with(), run_input=run_input())

    assert plan["tool"] is None


def test_a_client_asking_for_generation_gets_it():
    plan = prepare_a2ui_run(entity=agent_with(), run_input=run_input(forwarded_props={"injectA2UITool": True}))

    assert plan["tool"] is not None
    assert plan["tool"].name == GENERATE_A2UI_TOOL_NAME


def test_a_backend_can_opt_in_for_clients_that_do_not_ask():
    plan = prepare_a2ui_run(entity=agent_with(), run_input=run_input(), config={"inject_a2ui_tool": True})

    assert plan["tool"] is not None


def test_a_client_refusing_beats_a_backend_opt_in():
    plan = prepare_a2ui_run(
        entity=agent_with(),
        run_input=run_input(forwarded_props={"injectA2UITool": False}),
        config={"inject_a2ui_tool": True},
    )

    assert plan["tool"] is None


def test_generation_needs_a_model_to_run_the_subagent_on(caplog):
    entity = Agent(id="a", name="A")

    plan = prepare_a2ui_run(entity=entity, run_input=run_input(forwarded_props={"injectA2UITool": True}))

    assert plan["tool"] is None
    assert "no model" in caplog.text
    assert levels_logging(caplog, "no model") == {"WARNING"}


def test_a_malformed_forwarded_props_payload_is_tolerated():
    request = run_input()
    request.forwarded_props = "not a mapping"  # type: ignore[assignment]

    assert prepare_a2ui_run(entity=agent_with(), run_input=request)["tool"] is None


# =============================================================================
# The settings the interface is given
# =============================================================================


def test_a_misspelled_setting_is_refused():
    """Every one of these settings turns something on, so one that is ignored
    leaves the feature off with the configuration apparently in place."""
    with pytest.raises(ValueError) as refusal:
        AGUI(agent=agent_with(), a2ui={"inject_a2ui_tools": True})  # type: ignore[typeddict-unknown-key]

    assert "inject_a2ui_tools" in str(refusal.value)
    # The setting it was nearly spelled as, so the reader is not left to diff
    # their key against the list themselves.
    assert "inject_a2ui_tool'" in str(refusal.value)


def test_a_misspelled_setting_is_refused_by_the_planner_too():
    """The interface is not the only door in: the planner is what actually
    reads these, and another adapter's wiring calls it directly."""
    with pytest.raises(ValueError, match="default_catalog"):
        prepare_a2ui_run(
            entity=agent_with(),
            run_input=run_input(forwarded_props={"injectA2UITool": True}),
            config={"default_catalog": CATALOG_ID},  # type: ignore[typeddict-unknown-key]
        )


def test_settings_that_are_not_a_mapping_are_refused():
    with pytest.raises(ValueError, match="mapping"):
        AGUI(agent=agent_with(), a2ui=["inject_a2ui_tool"])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "wiring",
    [
        {"agent": RemoteAgent(base_url=UNREACHABLE, agent_id="remote-agent")},
        {"team": RemoteTeam(base_url=UNREACHABLE, team_id="remote-team")},
    ],
    ids=["remote-agent", "remote-team"],
)
def test_a2ui_settings_for_a_remote_entity_are_refused_where_they_are_written(wiring):
    """Per-run tools are not forwarded to a remote deployment, so no setting
    here can ever reach one. Refused at construction rather than warned about
    once per request, which leaves the configuration apparently in place."""
    with pytest.raises(ValueError, match="remote"):
        AGUI(a2ui={"inject_a2ui_tool": True}, **wiring)


def test_a_remote_entity_with_no_a2ui_settings_is_served_as_before():
    assert AGUI(agent=RemoteAgent(base_url=UNREACHABLE, agent_id="remote-agent")).a2ui is None


def test_every_documented_setting_is_accepted():
    """Refusing the unknown is only safe if the known set is the whole one."""
    documented: A2UIConfig = {
        "inject_a2ui_tool": True,
        "tool_name": "draw_ui",
        "tool_description": "Draw.",
        "default_surface_id": "sales",
        "default_catalog_id": CATALOG_ID,
        "catalog": {"components": []},
        "guidelines": {},
        "recovery": {"maxAttempts": 5},
        "on_a2ui_attempt": None,
        "tool_choice": "auto",
        "subagent_timeout": 300,
    }

    assert set(documented) == set(A2UIConfig.__annotations__)
    assert AGUI(agent=agent_with(), a2ui=documented).a2ui == documented


# =============================================================================
# Reading what was asked for
# =============================================================================


@pytest.mark.parametrize("spelling", ["false", "False", "FALSE", " false ", "0", "no", "off"])
def test_a_stringified_refusal_is_read_as_one(spelling):
    """A client that stringifies its booleans on the way out still means no.

    Read as a tool name instead, a refusal turns generation on and takes away
    a client tool called "false", which is neither what was asked for nor
    something the client has.
    """
    plan = prepare_a2ui_run(
        entity=agent_with(),
        run_input=run_input(forwarded_props={"injectA2UITool": spelling}),
        config={"inject_a2ui_tool": True},
    )

    assert plan["tool"] is None
    assert plan["drop_tool_names"] == []


@pytest.mark.parametrize("spelling", ["true", "True", "1", "yes", "on"])
def test_a_stringified_yes_is_read_as_one(spelling):
    """And the render tool replaced is the default one, not a tool named "true"."""
    plan = prepare_a2ui_run(entity=agent_with(), run_input=run_input(forwarded_props={"injectA2UITool": spelling}))

    assert plan["tool"] is not None
    assert plan["drop_tool_names"] == [RENDER_A2UI_TOOL_NAME]


@pytest.mark.parametrize("value", [0, 0.0, "", [], {}], ids=["zero", "float-zero", "empty", "list", "mapping"])
def test_a_falsy_refusal_beats_a_backend_opt_in(value, caplog):
    """The opt-out is a promise, so anything false the client sends is a no.

    Discarded as unreadable instead, the backend opt-in below applies and the
    client's refusal is gone: a client that has no boolean of its own and
    sends 0 is refused as surely as one that sends false.
    """
    plan = prepare_a2ui_run(
        entity=agent_with(),
        run_input=run_input(forwarded_props={"injectA2UITool": value}),
        config={"inject_a2ui_tool": True},
    )

    assert plan["tool"] is None
    assert plan["drop_tool_names"] == []


def test_a_stringified_refusal_in_the_backend_settings_is_read_as_one():
    """Backend settings arrive from a config file as readily as from Python."""
    plan = prepare_a2ui_run(entity=agent_with(), run_input=run_input(), config={"inject_a2ui_tool": "false"})

    assert plan["tool"] is None


@pytest.mark.parametrize("value", ["   ", 1, {"name": "render"}], ids=["blank", "int", "mapping"])
def test_a_value_that_is_neither_a_boolean_nor_a_tool_name_is_reported(value, caplog):
    """Not a choice to make quietly: read as a name it drops a tool nobody
    has, and read as a yes it enables what the client may have meant to refuse."""
    plan = prepare_a2ui_run(entity=agent_with(), run_input=run_input(forwarded_props={"injectA2UITool": value}))

    assert plan["tool"] is None
    assert levels_logging(caplog, "injectA2UITool") == {"WARNING"}


# =============================================================================
# Remote agents and teams
# =============================================================================


@pytest.mark.parametrize(
    "entity",
    [
        RemoteAgent(base_url=UNREACHABLE, agent_id="remote-agent"),
        RemoteTeam(base_url=UNREACHABLE, team_id="remote-team"),
    ],
    ids=["remote-agent", "remote-team"],
)
def test_a_remote_entity_keeps_the_a2ui_it_already_had(entity, caplog):
    """Per-run tools are not forwarded to a remote deployment, so injecting
    would take the client's render tool away and put nothing in its place."""
    plan = prepare_a2ui_run(entity=entity, run_input=run_input(forwarded_props={"injectA2UITool": True}))

    assert plan["tool"] is None
    assert plan["drop_tool_names"] == []
    # The catalog the client's own render tool needs the model to have read.
    assert [entry.description for entry in plan["context"]] == [A2UI_SCHEMA_CONTEXT_DESCRIPTION]
    assert "remote" in caplog.text
    assert levels_logging(caplog, "remote agent or team") == {"WARNING"}
    # A remote entity does have a model; it just is not exposed locally.
    assert "no model" not in caplog.text


# =============================================================================
# Never injecting over the developer's own wiring
# =============================================================================


def test_a_developer_wired_tool_is_not_duplicated():
    wired = get_a2ui_tools({"model": a_model()})

    plan = prepare_a2ui_run(entity=agent_with(wired), run_input=run_input(forwarded_props={"injectA2UITool": True}))

    assert plan["tool"] is None


def test_a_developer_wired_tool_under_another_name_is_still_recognized():
    wired = get_a2ui_tools({"model": a_model(), "tool_name": "draw_ui"})

    plan = prepare_a2ui_run(entity=agent_with(wired), run_input=run_input(forwarded_props={"injectA2UITool": True}))

    assert plan["tool"] is None


def test_a_hand_rolled_tool_of_the_same_name_is_respected():
    hand_rolled = Function(name=GENERATE_A2UI_TOOL_NAME, entrypoint=lambda: "")

    plan = prepare_a2ui_run(
        entity=agent_with(hand_rolled), run_input=run_input(forwarded_props={"injectA2UITool": True})
    )

    assert plan["tool"] is None


def test_a_developer_wired_tool_leaves_the_clients_render_tool_alone():
    """Opting out of managed wiring opts out of all of it."""
    wired = get_a2ui_tools({"model": a_model()})

    plan = prepare_a2ui_run(entity=agent_with(wired), run_input=run_input(forwarded_props={"injectA2UITool": True}))

    assert plan["drop_tool_names"] == []


def test_the_tool_can_be_renamed_by_configuration():
    plan = prepare_a2ui_run(
        entity=agent_with(),
        run_input=run_input(forwarded_props={"injectA2UITool": True}),
        config={"tool_name": "draw_ui"},
    )

    assert plan["tool"] is not None
    assert plan["tool"].name == "draw_ui"


# =============================================================================
# The two tool detectors, over every shape a tool can arrive in
# =============================================================================


def a_generation_function() -> Any:
    return get_a2ui_tools({"model": a_model()})


def a_toolkit_wrapping_the_generation_tool() -> Any:
    """A toolkit exposing a generation tool it was handed.

    Writing into ``functions`` is how a toolkit publishes a Function it did not
    derive from one of its own methods, and it is the dict the name detector
    reads.
    """
    toolkit = Toolkit(name="a2ui", auto_register=False)
    toolkit.functions[GENERATE_A2UI_TOOL_NAME] = a_generation_function()
    return toolkit


def a_callable_named_like_the_generation_tool() -> Any:
    def generate_a2ui() -> str:
        return ""

    generate_a2ui.__name__ = GENERATE_A2UI_TOOL_NAME
    return generate_a2ui


#: Every shape a tool reaches an entity in, and what one reading of the tools
#: can establish about it: whether the entity generates surfaces, and whether
#: the generation tool's name is taken. They are different questions -- three
#: of these shapes carry a tool of that name that generates nothing -- and a
#: factory answers neither, because reading it means running it.
TOOL_SHAPES: Dict[str, Any] = {
    "function": (lambda: agent_with(a_generation_function()), ToolPresence.PRESENT, ToolPresence.PRESENT),
    "toolkit": (
        lambda: agent_with(a_toolkit_wrapping_the_generation_tool()),
        ToolPresence.PRESENT,
        ToolPresence.PRESENT,
    ),
    "factory": (
        lambda: Agent(id="a", name="A", model=a_model(), tools=lambda: [a_generation_function()]),
        ToolPresence.UNKNOWN,
        ToolPresence.UNKNOWN,
    ),
    "bare-callable": (
        lambda: agent_with(a_callable_named_like_the_generation_tool()),
        ToolPresence.ABSENT,
        ToolPresence.PRESENT,
    ),
    "openai-nested-dict": (
        lambda: agent_with(
            {"type": "function", "function": {"name": GENERATE_A2UI_TOOL_NAME, "parameters": {"type": "object"}}}
        ),
        ToolPresence.ABSENT,
        ToolPresence.PRESENT,
    ),
    "flat-dict": (
        lambda: agent_with({"name": GENERATE_A2UI_TOOL_NAME, "parameters": {"type": "object"}}),
        ToolPresence.ABSENT,
        ToolPresence.PRESENT,
    ),
}

EVERY_TOOL_SHAPE = list(TOOL_SHAPES)


@pytest.mark.parametrize("shape", EVERY_TOOL_SHAPE)
def test_one_reading_of_the_tools_answers_both_questions(shape):
    """Both questions come off one walk of the tools list.

    They were two functions with independently written cases, and nothing
    required them to agree on one input: a shape one could read and the other
    could not was reported as a tool that is absent rather than one that
    cannot be seen, and each caller then made a different wrong decision from
    the same wrong answer.
    """
    build, generates, carries = TOOL_SHAPES[shape]
    tools = resolve_entity_tools(build())

    assert tools.generates_a2ui() is generates
    assert tools.carries(GENERATE_A2UI_TOOL_NAME) is carries


def test_a_shape_that_cannot_be_read_is_not_reported_as_empty():
    """The distinction the whole type exists for: nothing was ruled out, it was
    only not seen, and "absent" is the answer that cannot be given."""
    unreadable = resolve_entity_tools(Agent(id="a", name="A", model=a_model(), tools=lambda: []))
    read = resolve_entity_tools(agent_with())

    assert unreadable.generates_a2ui() is ToolPresence.UNKNOWN
    assert unreadable.carries("anything_at_all") is ToolPresence.UNKNOWN
    assert read.generates_a2ui() is ToolPresence.ABSENT
    assert read.carries("anything_at_all") is ToolPresence.ABSENT


@pytest.mark.parametrize("shape", EVERY_TOOL_SHAPE)
def test_a_tool_the_developer_wired_is_never_injected_over_whatever_shape_it_has(shape):
    """The promise the module docstring and the cookbook both make.

    Injecting over one leaves the run with two tools of the same name and takes
    the client's render tool away, so the model chooses between duplicates and
    the browser has nothing of its own left to draw with. A shape that cannot
    be read is declined for that reason: the duplicate is a run that cannot
    work, while declining leaves the developer's own wiring standing and says
    so in the log.
    """
    build, _, _ = TOOL_SHAPES[shape]

    plan = prepare_a2ui_run(entity=build(), run_input=run_input(forwarded_props={"injectA2UITool": True}))

    assert plan["tool"] is None
    assert plan["drop_tool_names"] == []


@pytest.mark.parametrize("shape", ["function", "toolkit", "factory"])
def test_a_run_that_may_generate_gets_the_render_channel(shape):
    """Recognizing the tool is what buys progressive painting.

    A run that generates a surface without this channel still commits the
    surface, so nothing fails: the surface simply appears whole, seconds later,
    and the loss is invisible from the outside. Which is why a shape that
    cannot be read gets one too, unlike injection: an unread channel costs a
    run nothing.
    """
    build, _, _ = TOOL_SHAPES[shape]

    plan = prepare_a2ui_run(entity=build(), run_input=run_input(forwarded_props={"injectA2UITool": True}))

    assert plan["run"].render_stream is not None


@pytest.mark.parametrize("shape", ["bare-callable", "openai-nested-dict", "flat-dict"])
def test_a_run_that_cannot_generate_gets_no_channel(shape):
    """A tool of that name which generates nothing is still only a name, and
    the channel exists for fragments the generation tool pushes."""
    build, _, _ = TOOL_SHAPES[shape]

    plan = prepare_a2ui_run(entity=build(), run_input=run_input(forwarded_props={"injectA2UITool": True}))

    assert plan["run"].render_stream is None


# =============================================================================
# Saying why generation was declined
# =============================================================================


def test_declining_because_a_tool_of_that_name_exists_says_so(caplog):
    """The client asked for generation and is getting none, and the tool that
    kept the name is not one this interface knows anything about."""
    hand_rolled = Function(name=GENERATE_A2UI_TOOL_NAME, entrypoint=lambda: "")

    plan = prepare_a2ui_run(
        entity=agent_with(hand_rolled), run_input=run_input(forwarded_props={"injectA2UITool": True})
    )

    assert plan["tool"] is None
    assert levels_logging(caplog, GENERATE_A2UI_TOOL_NAME) == {"WARNING"}


def test_declining_because_the_tools_cannot_be_read_says_so(caplog):
    """The one bail-out a developer can act on only if they are told: the
    remedy is to hand the tools over as a list, or to wire generation in."""
    entity = Agent(id="a", name="A", model=a_model(), tools=lambda: [])

    plan = prepare_a2ui_run(entity=entity, run_input=run_input(forwarded_props={"injectA2UITool": True}))

    assert plan["tool"] is None
    assert levels_logging(caplog, "callable") == {"WARNING"}


def test_leaving_the_developers_own_generation_tool_alone_is_not_a_warning(caplog, monkeypatch):
    """Wiring one is the documented path, so warning about it once per request
    would be noise. The record still exists for whoever reads a debug log."""
    monkeypatch.setattr(agno_log, "debug_on", True)
    caplog.set_level(logging.DEBUG, logger="agno")

    plan = prepare_a2ui_run(
        entity=agent_with(get_a2ui_tools({"model": a_model()})),
        run_input=run_input(forwarded_props={"injectA2UITool": True}),
    )

    assert plan["tool"] is None
    assert levels_logging(caplog, GENERATE_A2UI_TOOL_NAME) == {"DEBUG"}


# =============================================================================
# Replacing the render tool the client injected
# =============================================================================


def test_the_clients_render_tool_is_replaced():
    plan = prepare_a2ui_run(entity=agent_with(), run_input=run_input(forwarded_props={"injectA2UITool": True}))

    assert plan["drop_tool_names"] == [RENDER_A2UI_TOOL_NAME]


def test_a_client_naming_its_render_tool_has_that_one_replaced():
    plan = prepare_a2ui_run(
        entity=agent_with(), run_input=run_input(forwarded_props={"injectA2UITool": "paint_surface"})
    )

    assert plan["tool"] is not None
    assert plan["drop_tool_names"] == ["paint_surface"]


def test_a_client_tool_of_the_generation_tools_name_is_taken_out(caplog):
    """Agno keeps the first tool of a name and skips the rest, and this run's
    client tools are registered ahead of the injected one, so such a tool
    would leave the model calling the client and nothing generating here."""
    client_tools = [
        {
            "name": GENERATE_A2UI_TOOL_NAME,
            "description": "The client's own.",
            "parameters": {"type": "object", "properties": {}},
        }
    ]

    plan = prepare_a2ui_run(
        entity=agent_with(), run_input=run_input(tools=client_tools, forwarded_props={"injectA2UITool": True})
    )

    assert plan["tool"] is not None
    assert plan["drop_tool_names"] == [RENDER_A2UI_TOOL_NAME, GENERATE_A2UI_TOOL_NAME]
    assert levels_logging(caplog, "forwarded a tool named") == {"WARNING"}


def test_a_client_tool_that_collides_with_nothing_is_not_reported(caplog):
    plan = prepare_a2ui_run(entity=agent_with(), run_input=run_input(forwarded_props={"injectA2UITool": True}))

    assert plan["drop_tool_names"] == [RENDER_A2UI_TOOL_NAME]
    assert "forwarded a tool named" not in caplog.text


def test_the_guide_for_the_replaced_tool_is_dropped():
    context = [
        SCHEMA_ENTRY,
        {"description": render_guide_description(RENDER_A2UI_TOOL_NAME), "value": "call it like this"},
        {"description": "User preferences", "value": "USD"},
    ]

    plan = prepare_a2ui_run(
        entity=agent_with(), run_input=run_input(forwarded_props={"injectA2UITool": True}, context=context)
    )

    kept = [entry.description for entry in plan["context"]]
    assert kept == ["User preferences"]


def test_an_unrelated_guide_is_kept():
    context = [
        {"description": render_guide_description("someone_elses_tool"), "value": "call it like this"},
    ]

    plan = prepare_a2ui_run(
        entity=agent_with(), run_input=run_input(forwarded_props={"injectA2UITool": True}, context=context)
    )

    assert [entry.description for entry in plan["context"]] == [render_guide_description("someone_elses_tool")]


# =============================================================================
# The catalog
# =============================================================================


def test_the_catalog_is_taken_out_of_the_context_the_agent_sees():
    """When generation is injected the catalog reaches the render subagent
    through run state, and can run to thousands of tokens the planner cannot use."""
    plan = prepare_a2ui_run(entity=agent_with(), run_input=run_input(forwarded_props={"injectA2UITool": True}))

    assert [entry.description for entry in plan["context"]] == []
    assert json.loads(plan["run"].state["ag-ui"]["a2ui_schema"])["catalogId"] == CATALOG_ID


def test_the_catalog_stays_in_the_context_when_nothing_here_generates():
    """The client renders A2UI through its own render tool on such a run, and
    that tool only works if the component list reached the model."""
    plan = prepare_a2ui_run(entity=agent_with(), run_input=run_input())

    assert plan["tool"] is None
    assert [entry.description for entry in plan["context"]] == [A2UI_SCHEMA_CONTEXT_DESCRIPTION]
    assert json.loads(plan["run"].state["ag-ui"]["a2ui_schema"])["catalogId"] == CATALOG_ID


def test_the_catalog_is_taken_out_for_a_developer_wired_tool_too():
    """Whoever wired it, generation reads the catalog from run state, and the
    planner pays for it in every prompt for nothing."""
    wired = get_a2ui_tools({"model": a_model()})

    plan = prepare_a2ui_run(entity=agent_with(wired), run_input=run_input(forwarded_props={"injectA2UITool": True}))

    assert [entry.description for entry in plan["context"]] == []
    assert json.loads(plan["run"].state["ag-ui"]["a2ui_schema"])["catalogId"] == CATALOG_ID


def test_a_hand_wired_agent_is_spared_the_catalog_on_a_run_nobody_asked_about():
    """The client asks for injection per run; a hand-wired agent generates on
    every one of them, including the runs where nothing was asked."""
    wired = get_a2ui_tools({"model": a_model()})

    plan = prepare_a2ui_run(entity=agent_with(wired), run_input=run_input())

    assert [entry.description for entry in plan["context"]] == []


def test_the_catalog_stays_for_a_client_that_renders_a2ui_itself():
    """A run carrying the client's own render tool draws in the browser, and
    that only works if the component list reached the model."""
    wired = get_a2ui_tools({"model": a_model()})
    client_tools = [
        {
            "name": RENDER_A2UI_TOOL_NAME,
            "description": "Render an A2UI surface.",
            "parameters": {"type": "object", "properties": {}},
        }
    ]

    plan = prepare_a2ui_run(entity=agent_with(wired), run_input=run_input(tools=client_tools))

    assert [entry.description for entry in plan["context"]] == [A2UI_SCHEMA_CONTEXT_DESCRIPTION]


def test_context_without_a_catalog_is_passed_through():
    context = [{"description": "User preferences", "value": "USD"}]

    plan = prepare_a2ui_run(entity=agent_with(), run_input=run_input(context=context))

    assert [entry.description for entry in plan["context"]] == ["User preferences"]
    assert "a2ui_schema" not in plan["run"].state["ag-ui"]


async def test_the_forwarded_catalog_is_what_generated_surfaces_bind_to():
    """The catalog is baked into the tool this run gets, not only left in state.

    The tool is built per request precisely so it can carry this run's catalog,
    and the surface it commits has to name that one rather than the built-in
    default: a surface bound to a catalog the client never registered renders
    as nothing.
    """
    plan = prepare_a2ui_run(
        entity=agent_with(model=a_rendering_model()), run_input=run_input(forwarded_props={"injectA2UITool": True})
    )

    assert plan["tool"] is not None
    assert json.loads(plan["run"].state["ag-ui"]["a2ui_schema"])["catalogId"] == CATALOG_ID

    # Called with none of this run's inputs in scope, so what the planner put
    # on the tool is the only place a catalog can come from.
    envelope = json.loads(await plan["tool"].entrypoint(run_context=None))

    assert created_surface(envelope)["catalogId"] == CATALOG_ID


def test_the_client_history_travels_to_the_tool():
    """An earlier surface is found in what the client sent, because the agent's
    own run history only covers the turn in progress."""
    messages = [
        {"id": "m1", "role": "user", "content": "make a card"},
        {"id": "m2", "role": "tool", "toolCallId": "prior", "content": "{}"},
        {"id": "m3", "role": "user", "content": "make it red"},
    ]

    plan = prepare_a2ui_run(entity=agent_with(), run_input=run_input(messages=messages))

    assert [message.id for message in plan["run"].messages] == ["m1", "m2", "m3"]


# =============================================================================
# What the tool tells the model about itself
# =============================================================================


def test_only_the_intent_is_a_required_argument():
    """A provider in strict mode reads a missing 'required' as "all of them",
    which would make creating a surface impossible without an update's arguments."""
    tool = get_a2ui_tools({"model": a_model()})

    assert tool.parameters["required"] == ["intent"]


def test_the_arguments_an_update_needs_stay_optional():
    tool = get_a2ui_tools({"model": a_model()})

    optional = set(tool.parameters["properties"]) - set(tool.parameters["required"])
    assert optional == {"target_surface_id", "changes"}


def test_the_declaration_survives_the_processing_every_run_does():
    """A run processes its own copy of the tool, honouring the tool's own
    strict setting over the run's, which is what keeps this schema as written."""
    tool = get_a2ui_tools({"model": a_model()})
    per_run = tool._per_run_copy()

    # What agno.agent._tools does with each tool of a run whose other tools go
    # out strict: the tool's own setting wins where it has one.
    per_run.process_entrypoint(strict=True if per_run.strict is None else per_run.strict)

    assert per_run.parameters["required"] == ["intent"]


def test_the_tool_is_not_declared_strict_to_the_provider():
    """A strict schema must require every property, and this one cannot.

    Two of the three arguments describe an edit, so a run whose other tools go
    out strict must not carry this one's schema rebuilt to match: the model
    would have to supply an edit's arguments to create a first surface. What
    keeps the declaration is the tool saying it is not strict, so the run
    never processes it that way to begin with.
    """
    tool = get_a2ui_tools({"model": a_model()})

    assert tool.strict is False
    assert tool.to_dict()["strict"] is False


def test_processing_one_runs_schema_leaves_the_next_runs_alone():
    """Runs share the tool's definition, never its schema.

    Both the strict rewrite and one provider adapter assign ``required`` in
    place, so a schema shared between runs would carry the first run's
    processing into every later one for the life of the process, and a
    declaration the tool makes once would be gone from the second request on.
    """
    tool = get_a2ui_tools({"model": a_model()})
    per_run = tool._per_run_copy()

    # What one provider adapter does to the schema it is handed: assign
    # ``required`` from ``properties``, in place.
    per_run.parameters["required"] = list(per_run.parameters["properties"])
    per_run.process_entrypoint(strict=True)

    assert tool.parameters["required"] == ["intent"]
    assert tool._per_run_copy().parameters["required"] == ["intent"]
    assert get_a2ui_tools({"model": a_model()}).parameters is not tool.parameters


# =============================================================================
# The module's own surface
# =============================================================================


def test_everything_this_module_is_imported_for_is_exported():
    """``__all__`` is the module's contract, and importers of these names
    include the router, the interface's own tests and any custom wiring."""
    exported = set(a2ui_module.__all__)

    for name in exported:
        assert hasattr(a2ui_module, name), name

    imported_elsewhere = {
        "OPENAI_RENDER_TOOL_CHOICE",
        "RENDER_A2UI_TOOL_NAME",
        "agui_state_from_dependencies",
        "classify_a2ui_subagent_error",
        "get_a2ui_tools",
        "prepare_a2ui_run",
        "render_guide_description",
        "stream_render_subagent",
        "strip_in_flight_tool_call",
    }
    assert imported_elsewhere <= exported


# =============================================================================
# When the toolkit cannot be imported
# =============================================================================


def test_a_missing_toolkit_says_to_install_it():
    message = a2ui_module._toolkit_import_message(
        ModuleNotFoundError("No module named 'ag_ui_a2ui_toolkit'", name="ag_ui_a2ui_toolkit")
    )

    assert "not installed" in message
    assert "pip install -U ag-ui-a2ui-toolkit" in message


def test_a_toolkit_too_old_to_import_from_is_not_called_missing():
    """Reporting this as "not installed" sends someone to reinstall a package
    they already have, and throws away the name that could not be found."""
    message = a2ui_module._toolkit_import_message(
        ImportError("cannot import name 'run_a2ui_generation_with_recovery' from 'ag_ui_a2ui_toolkit'")
    )

    assert "not installed" not in message
    assert "run_a2ui_generation_with_recovery" in message


def without_the_toolkit(monkeypatch: Any) -> None:
    """Make importing A2UI support fail the way an absent toolkit does.

    The tests in this file need the toolkit to run at all, so the branch the
    router takes without it is unreachable by uninstalling anything. Replacing
    the module with one that has no ``prepare_a2ui_run`` reaches it: that
    import is what fails, and it fails the same way for a toolkit that is
    missing and one too old to import from.
    """
    monkeypatch.setitem(sys.modules, "agno.os.interfaces.agui.a2ui", types.ModuleType("agno.os.interfaces.agui.a2ui"))


async def test_the_router_reports_why_the_toolkit_import_failed(caplog, monkeypatch):
    """The fallback runs without A2UI either way, but the reason it took that
    path is the only clue the operator gets."""
    without_the_toolkit(monkeypatch)

    events = await collect(StubEntity(one_text_chunk), run_input(forwarded_props={"injectA2UITool": True}))

    assert [event.type for event in events][-1] == EventType.RUN_FINISHED
    assert "prepare_a2ui_run" in caplog.text
    # The level is part of what the README promises an operator, and the README
    # now says error, so the two are pinned to each other here.
    assert levels_logging(caplog, "could not be imported") == {"ERROR"}


async def test_without_the_toolkit_the_clients_own_render_tool_is_left_standing(monkeypatch):
    """Nothing server-side can generate a surface on such a run, so the render
    tool the client injected is the only way one gets drawn. Replacing it here
    would leave the run with no way to render at all, and the catalog has to
    stay in the context the model reads for the same reason."""
    without_the_toolkit(monkeypatch)
    entity = RecordingEntity(one_text_chunk)

    events = await collect(
        entity,
        run_input(
            forwarded_props={"injectA2UITool": True},
            tools=[{"name": RENDER_A2UI_TOOL_NAME, "description": "Render.", "parameters": {"type": "object"}}],
        ),
    )

    assert [event.type for event in events][-1] == EventType.RUN_FINISHED
    run_context = entity.kwargs["run_context"]
    assert [tool.name for tool in run_context.client_tools or []] == [RENDER_A2UI_TOOL_NAME]
    assert list(run_context.dependencies or {}) == [A2UI_SCHEMA_CONTEXT_DESCRIPTION]


def with_a_broken_a2ui_module(monkeypatch: Any, error: BaseException) -> None:
    """Make importing A2UI support fail the way a broken module body does.

    Anything raised while the module runs reaches the importer, not just the
    ``ImportError`` an absent toolkit raises: a toolkit whose import has a side
    effect that fails, a syntax error in an installed build, a bad value in a
    module-level constant. A module whose attribute access raises reproduces
    every one of them at the same place: the ``from`` that reads the name.
    """
    module = types.ModuleType("agno.os.interfaces.agui.a2ui")

    def raise_it(name: str) -> Any:
        raise error

    module.__getattr__ = raise_it  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "agno.os.interfaces.agui.a2ui", module)


async def test_a_run_that_never_asked_for_a2ui_survives_a_broken_module(caplog, monkeypatch):
    """A2UI is an optional extra, and this call sits on the path of every run.

    Almost no AG-UI traffic asks for generation, so a failure that escapes here
    fails every ordinary request: whatever the run was for, the client gets
    RUN_ERROR and nothing else.
    """
    with_a_broken_a2ui_module(monkeypatch, RuntimeError("a2ui module body blew up"))

    events = await collect(StubEntity(one_text_chunk), run_input())

    assert [event.type for event in events][-1] == EventType.RUN_FINISHED
    assert EventType.RUN_ERROR not in [event.type for event in events]
    # Installed and broken is not the ordinary absent-extra case, so it is
    # still reported, at the level of something this run did not need.
    assert levels_logging(caplog, "a2ui module body blew up") == {"WARNING"}


async def test_a_broken_a2ui_module_is_reported_to_the_run_that_wanted_it(caplog, monkeypatch):
    """The run goes on without generation, so the log is the only account of
    why the surface the client asked for never came."""
    with_a_broken_a2ui_module(monkeypatch, RuntimeError("a2ui module body blew up"))

    events = await collect(StubEntity(one_text_chunk), run_input(forwarded_props={"injectA2UITool": True}))

    assert [event.type for event in events][-1] == EventType.RUN_FINISHED
    assert "a2ui module body blew up" in caplog.text
    assert levels_logging(caplog, "a2ui module body blew up") == {"ERROR"}


async def test_a_run_that_never_asked_for_generation_says_nothing_about_the_toolkit(caplog, monkeypatch):
    """The toolkit is an extra almost nobody installs, and a run that does not
    want generation loses nothing by its absence: reporting it would put an
    error in the log for every ordinary request."""
    without_the_toolkit(monkeypatch)

    events = await collect(StubEntity(one_text_chunk), run_input())

    assert [event.type for event in events][-1] == EventType.RUN_FINISHED
    assert "could not be imported" not in caplog.text


# =============================================================================
# Over the wire
# =============================================================================


def _chunk(delta: Dict[str, Any]) -> Any:
    from openai.types.chat import ChatCompletionChunk

    return ChatCompletionChunk.model_validate(
        {
            "id": "c",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "m",
            "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
        }
    )


def _call(name: Optional[str], arguments: str, call_id: Optional[str] = None) -> Dict[str, Any]:
    function: Dict[str, Any] = {"arguments": arguments}
    if name is not None:
        function["name"] = name
    frame: Dict[str, Any] = {"index": 0, "function": function}
    if call_id is not None:
        frame["id"] = call_id
        frame["type"] = "function"
    return {"tool_calls": [frame]}


def build_app(
    offered: List[List[str]],
    a2ui: Optional[Dict[str, Any]] = None,
    as_team: bool = False,
    schemas: Optional[List[Dict[str, Any]]] = None,
) -> Any:
    """An AG-UI app whose model records the tools it was offered each turn.

    ``schemas`` collects the tool definitions as the provider received them,
    which is the only place the schema a run actually sends can be read.
    """
    pytest.importorskip("openai")
    from agno.models.openai import OpenAIChat

    turns = {"n": 0}

    class PlannerModel(OpenAIChat):
        async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:  # type: ignore[override]
            turns["n"] += 1
            sent = kwargs.get("tools") or []
            offered.append(sorted(tool["function"]["name"] for tool in sent))
            if schemas is not None:
                schemas.extend(sent)
            if turns["n"] == 1 and GENERATE_A2UI_TOOL_NAME in offered[-1]:
                yield self._parse_provider_response_delta(_chunk(_call(GENERATE_A2UI_TOOL_NAME, "{}", call_id="outer")))
            elif turns["n"] == 2:
                yield self._parse_provider_response_delta(
                    _chunk(
                        _call(
                            RENDER_A2UI_TOOL_NAME,
                            json.dumps({"surfaceId": "sales", "components": COMPONENTS}),
                            call_id="inner",
                        )
                    )
                )
            else:
                yield self._parse_provider_response_delta(_chunk({"content": "Here you go."}))

    model = PlannerModel(id="m", api_key="x")
    agent = Agent(id="a2ui-agent", name="A2UI Agent", model=model)
    if as_team:
        team = Team(id="a2ui-team", name="A2UI Team", members=[agent], model=model)
        return AgentOS(id="a2ui-os", teams=[team], interfaces=[AGUI(team=team, a2ui=a2ui)]).get_app()
    return AgentOS(id="a2ui-os", agents=[agent], interfaces=[AGUI(agent=agent, a2ui=a2ui)]).get_app()


def post(app: Any, body: Dict[str, Any]) -> List[Dict[str, Any]]:
    """POST an AG-UI request and return the events the server sent.

    A run reports its own failure in band, so the 200 says only that the
    response started. The check belongs here rather than in each caller: a run
    that produced the tool result and then blew up leaves a test that forgot it
    green.
    """
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        response = client.post("/agui", json=body)

    assert response.status_code == 200
    events = []
    for line in response.text.split("\n"):
        line = line.strip()
        if line.startswith("data:"):
            events.append(json.loads(line[5:].strip()))

    errors = [event for event in events if event.get("type") == "RUN_ERROR"]
    assert not errors, f"the run failed in band: {errors}"
    return events


def wire_body(**forwarded_props: Any) -> Dict[str, Any]:
    return {
        "threadId": "thread-1",
        "runId": "run-1",
        "state": None,
        "messages": [{"id": "m1", "role": "user", "content": "show me a sales card"}],
        # The client injects its render tool alongside asking for generation.
        "tools": [
            {
                "name": RENDER_A2UI_TOOL_NAME,
                "description": "Render an A2UI surface.",
                "parameters": {"type": "object", "properties": {}},
            }
        ],
        "context": [
            SCHEMA_ENTRY,
            {"description": render_guide_description(RENDER_A2UI_TOOL_NAME), "value": "how to call it"},
        ],
        "forwardedProps": forwarded_props,
    }


def test_an_asking_client_gets_a_generated_surface():
    offered: List[List[str]] = []
    events = post(build_app(offered), wire_body(injectA2UITool=True))

    types = [event.get("type") for event in events]
    assert "RUN_ERROR" not in types

    # The generation tool replaced the client's render tool, so the run never
    # pauses waiting for the browser to draw anything.
    assert offered[0] == [GENERATE_A2UI_TOOL_NAME]

    results = [event for event in events if event.get("type") == "TOOL_CALL_RESULT"]
    envelope = json.loads(results[0]["content"])
    operations = {key: value for entry in envelope["a2ui_operations"] for key, value in entry.items()}
    assert operations["createSurface"] == {"surfaceId": "sales", "catalogId": CATALOG_ID}
    assert operations["updateComponents"]["components"] == COMPONENTS


def test_a_client_cannot_take_server_generation_away_by_naming_a_tool_after_it():
    """The whole run, with a client tool of the generation tool's own name."""
    offered: List[List[str]] = []
    body = wire_body(injectA2UITool=True)
    body["tools"].append(
        {
            "name": GENERATE_A2UI_TOOL_NAME,
            "description": "The client's own.",
            "parameters": {"type": "object", "properties": {}},
        }
    )

    events = post(build_app(offered), body)

    assert offered[0] == [GENERATE_A2UI_TOOL_NAME]
    results = [event for event in events if event.get("type") == "TOOL_CALL_RESULT"]
    assert len(results) == 1, "the client's tool won and nothing generated here"
    envelope = json.loads(results[0]["content"])
    assert created_surface(envelope)["catalogId"] == CATALOG_ID


def test_the_declared_arguments_are_what_a_real_run_sends():
    """What the builder wrote is not by itself what a provider receives: every
    run copies the tool and processes that copy. Losing the declaration makes
    both edit arguments mandatory, and a model that has to supply them cannot
    create a first surface at all."""
    offered: List[List[str]] = []
    schemas: List[Dict[str, Any]] = []

    post(build_app(offered, schemas=schemas), wire_body(injectA2UITool=True))

    generation = next(tool for tool in schemas if tool["function"]["name"] == GENERATE_A2UI_TOOL_NAME)
    assert generation["function"]["parameters"]["required"] == ["intent"]
    assert generation["function"].get("strict") is not True


def test_a_refusing_client_gets_an_ordinary_answer():
    offered: List[List[str]] = []
    events = post(build_app(offered, a2ui={"inject_a2ui_tool": True}), wire_body(injectA2UITool=False))

    assert GENERATE_A2UI_TOOL_NAME not in offered[0]
    # The client's own render tool is left exactly as it sent it.
    assert offered[0] == [RENDER_A2UI_TOOL_NAME]
    assert [event.get("type") for event in events].count("TOOL_CALL_RESULT") == 0
    contents = [event["delta"] for event in events if event.get("type") == "TEXT_MESSAGE_CONTENT"]
    assert contents == ["Here you go."]


def test_a_backend_opt_in_generates_without_the_client_asking():
    offered: List[List[str]] = []
    events = post(build_app(offered, a2ui={"inject_a2ui_tool": True}), wire_body())

    assert offered[0] == [GENERATE_A2UI_TOOL_NAME]
    assert [event.get("type") for event in events].count("TOOL_CALL_RESULT") == 1


def test_a_configured_catalog_overrides_the_forwarded_one():
    offered: List[List[str]] = []
    events = post(
        build_app(offered, a2ui={"default_catalog_id": "host-catalog"}),
        wire_body(injectA2UITool=True),
    )

    # Choosing a catalog server-side changes nothing about the wiring: the
    # generation tool still stands in for the client's render tool.
    assert offered[0] == [GENERATE_A2UI_TOOL_NAME]

    results = [event for event in events if event.get("type") == "TOOL_CALL_RESULT"]
    envelope = json.loads(results[0]["content"])
    operations = {key: value for entry in envelope["a2ui_operations"] for key, value in entry.items()}
    assert operations["createSurface"]["catalogId"] == "host-catalog"


def test_without_a_forwarded_catalog_the_basic_one_is_used():
    offered: List[List[str]] = []
    body = wire_body(injectA2UITool=True)
    body["context"] = []
    events = post(build_app(offered), body)

    assert offered[0] == [GENERATE_A2UI_TOOL_NAME]

    results = [event for event in events if event.get("type") == "TOOL_CALL_RESULT"]
    envelope = json.loads(results[0]["content"])
    operations = {key: value for entry in envelope["a2ui_operations"] for key, value in entry.items()}
    assert operations["createSurface"]["catalogId"] == BASIC_CATALOG_ID


# =============================================================================
# Teams
# =============================================================================


def test_a_team_gets_the_generation_tool_too():
    """Nothing about generation is agent-specific, and a team is the entity a
    client is likeliest to be talking to when it asks for a surface."""
    team = Team(id="t", name="T", members=[agent_with()], model=a_model())

    plan = prepare_a2ui_run(entity=team, run_input=run_input(forwarded_props={"injectA2UITool": True}))

    assert plan["tool"] is not None
    assert plan["tool"].name == GENERATE_A2UI_TOOL_NAME
    assert plan["drop_tool_names"] == [RENDER_A2UI_TOOL_NAME]
    # The catalog moves into run state on a team run for the same reason as on
    # an agent run: the planner cannot use it and pays for it in every prompt.
    assert [entry.description for entry in plan["context"]] == []
    assert json.loads(plan["run"].state["ag-ui"]["a2ui_schema"])["catalogId"] == CATALOG_ID


def test_a_team_generates_a_surface_over_the_wire():
    """The team's own model runs the render subagent, and its delegation tool
    is left alone: only the client's render tool is taken away."""
    offered: List[List[str]] = []
    events = post(build_app(offered, as_team=True), wire_body(injectA2UITool=True))

    types = [event.get("type") for event in events]
    assert "RUN_ERROR" not in types
    assert GENERATE_A2UI_TOOL_NAME in offered[0]
    assert RENDER_A2UI_TOOL_NAME not in offered[0]

    results = [event for event in events if event.get("type") == "TOOL_CALL_RESULT"]
    envelope = json.loads(results[0]["content"])
    operations = {key: value for entry in envelope["a2ui_operations"] for key, value in entry.items()}
    assert operations["createSurface"] == {"surfaceId": "sales", "catalogId": CATALOG_ID}
    assert operations["updateComponents"]["components"] == COMPONENTS


def test_a_members_generation_tool_is_not_injected_over():
    """A member's tool is this team's generation: a second one on the leader
    leaves the model choosing between duplicates and takes the client's render
    tool away for a run that now generates twice."""
    member = agent_with(get_a2ui_tools({"model": a_model()}))
    team = Team(id="t", name="T", members=[member], model=a_model())

    plan = prepare_a2ui_run(entity=team, run_input=run_input(forwarded_props={"injectA2UITool": True}))

    assert plan["tool"] is None
    # A member's surface paints while it is written like any other, so the
    # channel that carries the progress is prepared.
    assert plan["run"].render_stream is not None


def test_a_nested_teams_generation_tool_is_seen_too():
    member = agent_with(get_a2ui_tools({"model": a_model()}))
    inner = Team(id="i", name="I", members=[member], model=a_model())
    team = Team(id="t", name="T", members=[inner], model=a_model())

    assert resolve_entity_tools(team).generates_a2ui() is ToolPresence.PRESENT


def test_a_member_whose_own_tools_cannot_be_read_is_not_reported_as_absent(caplog):
    """A member's tools can be a callable it resolves when it runs, which is
    as unreadable as the leader's own and rules nothing out."""
    member = Agent(id="m", name="M", model=a_model(), tools=lambda: [])
    team = Team(id="t", name="T", members=[member], model=a_model())

    reading = resolve_entity_tools(team)
    assert reading.generates_a2ui() is ToolPresence.UNKNOWN
    # The leader's own list was read, so a name collision is still answerable.
    assert reading.carries(GENERATE_A2UI_TOOL_NAME) is ToolPresence.ABSENT

    plan = prepare_a2ui_run(entity=team, run_input=run_input(forwarded_props={"injectA2UITool": True}))

    assert plan["tool"] is None
    assert levels_logging(caplog, "cannot be known without running it") == {"WARNING"}


def test_members_given_as_a_callable_cannot_be_read_either():
    team = Team(id="t", name="T", members=lambda: [agent_with()], model=a_model())

    assert resolve_entity_tools(team).generates_a2ui() is ToolPresence.UNKNOWN


def test_a_members_tool_name_is_not_the_leaders():
    """The injected tool goes to the leader, so what a member calls its own
    tools cannot collide with it."""
    member = agent_with(Function(name=GENERATE_A2UI_TOOL_NAME, entrypoint=lambda: ""))
    team = Team(id="t", name="T", members=[member], model=a_model())

    plan = prepare_a2ui_run(entity=team, run_input=run_input(forwarded_props={"injectA2UITool": True}))

    assert plan["tool"] is not None


def test_a_remote_member_is_never_asked_what_tools_it_has():
    """Reading a remote member's tools is an HTTP round trip per request, to
    learn about tools that run in the remote deployment and cannot serve this
    run whatever they are."""
    remote = RemoteAgent(base_url=UNREACHABLE, agent_id="remote-member")
    team = Team(id="t", name="T", members=[remote], model=a_model())

    plan = prepare_a2ui_run(entity=team, run_input=run_input(forwarded_props={"injectA2UITool": True}))

    assert plan["tool"] is not None


# =============================================================================
# The path the tool is run on
# =============================================================================


def _a_generation_call() -> Any:
    from agno.tools.function import FunctionCall

    return FunctionCall(function=get_a2ui_tools({"model": a_rendering_model()}), arguments={"intent": "create"})


def test_the_synchronous_tool_path_is_refused():
    """Agno's synchronous path keeps whatever the entrypoint returns, so a
    coroutine nobody awaited would be handed to the model as the result."""
    from agno.exceptions import AgentRunException

    with pytest.raises(AgentRunException, match="synchronous"):
        _a_generation_call().execute()


async def test_the_synchronous_tool_path_is_refused_from_inside_a_running_loop():
    """A synchronous run driven from inside a loop still takes that path, so a
    loop is running says nothing about which path the call is on."""
    from agno.exceptions import AgentRunException

    with pytest.raises(AgentRunException, match="synchronous"):
        _a_generation_call().execute()


async def test_the_asynchronous_tool_path_is_left_alone():
    result = await _a_generation_call().aexecute()

    assert result.status == "success"
    assert created_surface(json.loads(result.result))["surfaceId"] == "sales"


# =============================================================================
# When the run fails
# =============================================================================


class StubEntity:
    """The least an entity can be: ``run_entity`` only ever calls ``arun``."""

    def __init__(self, chunks: Callable[[], AsyncIterator[Any]]) -> None:
        self._chunks = chunks

    def arun(self, **kwargs: Any) -> AsyncIterator[Any]:
        return self._chunks()


class RecordingEntity(StubEntity):
    """The same, keeping what the router ran it with."""

    def __init__(self, chunks: Callable[[], AsyncIterator[Any]]) -> None:
        super().__init__(chunks)
        self.kwargs: Dict[str, Any] = {}

    def arun(self, **kwargs: Any) -> AsyncIterator[Any]:
        self.kwargs = kwargs
        return super().arun(**kwargs)


async def one_text_chunk() -> AsyncIterator[Any]:
    yield RunContentEvent(content="Here you go.")


async def text_then_failure() -> AsyncIterator[Any]:
    yield RunContentEvent(content="Working on it")
    raise RuntimeError("model connection dropped")


async def tool_call_then_failure() -> AsyncIterator[Any]:
    yield ToolCallStartedEvent(tool=ToolExecution(tool_call_id="call_1", tool_name="lookup", tool_args={}))
    raise RuntimeError("model connection dropped")


async def collect(entity: Any, request: RunAgentInput, **kwargs: Any) -> List[Any]:
    return [event async for event in run_entity(entity, request, **kwargs)]  # type: ignore[arg-type]


async def test_a_failure_while_arranging_a2ui_reaches_the_client(monkeypatch):
    """Otherwise the response body just stops: a 200 with no error in it."""

    def explode(**kwargs: Any) -> Any:
        raise ValueError("malformed catalog")

    monkeypatch.setattr("agno.os.interfaces.agui.a2ui.prepare_a2ui_run", explode)

    events = await collect(StubEntity(one_text_chunk), run_input())

    assert [event.type for event in events] == [EventType.RUN_STARTED, EventType.RUN_ERROR]
    assert "malformed catalog" in events[-1].message


async def test_a_failure_mid_stream_closes_the_open_text_message():
    events = await collect(StubEntity(text_then_failure), run_input())

    types = [event.type for event in events]
    assert types == [
        EventType.RUN_STARTED,
        EventType.TEXT_MESSAGE_START,
        EventType.TEXT_MESSAGE_CONTENT,
        EventType.TEXT_MESSAGE_END,
        EventType.RUN_ERROR,
    ]
    assert events[-2].message_id == events[1].message_id


async def test_a_failure_mid_stream_closes_the_open_tool_call():
    events = await collect(StubEntity(tool_call_then_failure), run_input())

    types = [event.type for event in events]
    assert types[-2:] == [EventType.TOOL_CALL_END, EventType.RUN_ERROR]
    assert events[-2].tool_call_id == "call_1"
    assert types.count(EventType.TEXT_MESSAGE_START) == types.count(EventType.TEXT_MESSAGE_END)


async def cancelled_mid_tool_call() -> AsyncIterator[Any]:
    """A run cancelled with a tool call open, as an abandoned generation is.

    The A2UI classifier raises cancellation deliberately, for a caller that has
    gone and for a render turn that outran its deadline, and it reaches the
    router through the stream like any other failure.
    """
    yield ToolCallStartedEvent(tool=ToolExecution(tool_call_id="call_1", tool_name="generate_a2ui", tool_args={}))
    raise asyncio.CancelledError("caller disconnected; abandoning A2UI generation")


async def collect_until(entity: Any, request: RunAgentInput, raises: type) -> List[Any]:
    events: List[Any] = []
    with pytest.raises(raises):
        async for event in run_entity(entity, request):  # type: ignore[arg-type]
            events.append(event)
    return events


async def test_a_cancelled_run_still_ends_what_it_opened():
    """Cancellation is not an ``Exception``, so the error path cannot see it.

    Unhandled, the run unwinds with no terminal event at all: the client is
    left holding an open tool call on a stream that simply stops, and the
    cancel is what the client asked for in the first place.
    """
    events = await collect_until(StubEntity(cancelled_mid_tool_call), run_input(), asyncio.CancelledError)

    types = [event.type for event in events]
    assert types[-2:] == [EventType.TOOL_CALL_END, EventType.RUN_ERROR]
    assert events[-2].tool_call_id == "call_1"
    assert "abandoning A2UI generation" in events[-1].message


async def test_a_failure_finalizing_the_run_does_not_escape_or_skip_the_reset(caplog, monkeypatch):
    """Cleanup runs on the way out of every run, including a healthy one.

    Raising there hands ASGI an exception with the response already sent, and
    it skips the rest of the block: the context variable stays set on a context
    the server reuses, so the next run served on it reads this run's A2UI
    inputs.
    """

    def a_stream_that_fails_to_close(**kwargs: Any) -> AsyncIterator[Any]:
        async def events() -> AsyncIterator[Any]:
            try:
                yield RunStartedEvent(type=EventType.RUN_STARTED, thread_id="thread-1", run_id="run-1")
                yield RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id="thread-1", run_id="run-1")
            except GeneratorExit:
                raise RuntimeError("finalizing the agent stream failed")

        return events()

    monkeypatch.setattr(
        "agno.os.interfaces.agui.router.async_stream_agno_response_as_agui_events",
        a_stream_that_fails_to_close,
    )

    stream = run_entity(StubEntity(one_text_chunk), run_input())  # type: ignore[arg-type]
    # Far enough in that the stream is suspended and the token is set.
    await stream.__anext__()
    await stream.__anext__()

    await stream.aclose()

    assert current_a2ui_run.get() is None
    assert "finalizing the agent stream failed" in caplog.text


async def test_cleanup_survives_a_stream_finalized_in_another_context():
    """An async generator borrows whatever context drives it, so the context the
    A2UI inputs were set in is not always the one that finalizes the stream.

    The token cannot be reset from here, and the reset raising would abandon
    the rest of the cleanup. So the run still has to be finalized, which is
    what a close that quietly gave up would also satisfy if nothing said what
    finalizing means.
    """
    finalized = asyncio.Event()
    run_seen_while_driving: List[Any] = []

    async def one_text_chunk_then_finalize() -> AsyncIterator[Any]:
        try:
            run_seen_while_driving.append(current_a2ui_run.get())
            yield RunContentEvent(content="Here you go.")
        finally:
            finalized.set()

    stream = run_entity(StubEntity(one_text_chunk_then_finalize), run_input())  # type: ignore[arg-type]

    async def start() -> None:
        # Far enough in that the A2UI context variable has been set.
        await stream.__anext__()
        await stream.__anext__()

    await asyncio.create_task(start())

    await stream.aclose()

    # The scenario, not just its outcome: the run was visible in the context
    # that drove the stream and never in this one.
    assert run_seen_while_driving and run_seen_while_driving[0] is not None
    assert current_a2ui_run.get() is None
    assert finalized.is_set()
