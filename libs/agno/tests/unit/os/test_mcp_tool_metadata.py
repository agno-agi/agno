"""Unit tests for the presentation metadata MCP tools publish: ``title`` and ``annotations``.

Assistant marketplaces read this metadata when they review a listing: a submission scan
rejects tools that carry no annotations, and reviewers test the hints against what the
tool actually does. These tests cover the three paths that put a tool on the server --
exposed components, custom tools, and the built-ins -- plus the validation that stops a
misspelled hint from reaching a client as "no such annotation".

The FastMCP tool surface is exercised with an in-memory client, matching
test_mcp_exposed_components.py.
"""

import pytest

pytest.importorskip("fastmcp")

from typing import Optional  # noqa: E402

from fastmcp import Client  # noqa: E402

import agno.os.mcp as mcp_mod  # noqa: E402
from agno.agent import Agent  # noqa: E402
from agno.os import AgentOS, MCPConfig  # noqa: E402
from agno.os.mcp import build_mcp_server  # noqa: E402
from agno.tools import tool  # noqa: E402
from agno.tools.function import Function  # noqa: E402


def _agent(id: str = "chief", name: Optional[str] = "Chief of Staff") -> Agent:
    return Agent(id=id, name=name, description="Runs the day.")


async def _tools_by_name(os: AgentOS) -> dict:
    async with Client(build_mcp_server(os)) as client:
        return {t.name: t for t in await client.list_tools()}


async def _tool_by_name(os: AgentOS, name: str):
    return (await _tools_by_name(os))[name]


# --------------------------------------------------------------------------------------
# Exposed components
# --------------------------------------------------------------------------------------


async def test_bare_component_titles_from_its_name_and_carries_default_annotations():
    """A published component says what a run does before the deployer says anything:
    not read-only, potentially destructive, reaching beyond this server."""
    agent = _agent()
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent]))

    published = await _tool_by_name(os, "chief")

    assert published.title == "Chief of Staff"
    assert published.annotations.readOnlyHint is False
    assert published.annotations.destructiveHint is True
    assert published.annotations.openWorldHint is True


async def test_as_tool_overrides_title_and_merges_annotations_per_key():
    """The override replaces only the keys it names; the rest of the defaults stand."""
    agent = _agent()
    os = AgentOS(
        agents=[agent],
        mcp=MCPConfig(
            default_tools=False,
            tools=[agent.as_tool(name="ask_chief", title="Ask the Chief", annotations={"readOnlyHint": True})],
        ),
    )

    published = await _tool_by_name(os, "ask_chief")

    assert published.title == "Ask the Chief"
    assert published.annotations.readOnlyHint is True
    # untouched by the override, so still the surface default
    assert published.annotations.destructiveHint is True
    assert published.annotations.openWorldHint is True


async def test_annotation_set_to_none_removes_the_default_instead_of_publishing_null():
    """The way to publish a tool WITHOUT a hint the surface would otherwise assert."""
    agent = _agent()
    os = AgentOS(
        agents=[agent],
        mcp=MCPConfig(default_tools=False, tools=[agent.as_tool(annotations={"destructiveHint": None})]),
    )

    published = await _tool_by_name(os, "chief")

    assert published.annotations.destructiveHint is None
    assert published.annotations.openWorldHint is True


async def test_title_falls_back_to_the_tool_name_when_the_component_is_unnamed():
    agent = _agent(id="chief", name=None)
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent]))

    assert (await _tool_by_name(os, "chief")).title == "chief"


async def test_title_is_mirrored_into_annotations_for_older_clients():
    """A client reading either title slot must be shown the same name."""
    agent = _agent()
    os = AgentOS(
        agents=[agent],
        mcp=MCPConfig(default_tools=False, tools=[agent.as_tool(title="Ask the Chief")]),
    )

    published = await _tool_by_name(os, "chief")

    assert published.title == "Ask the Chief"
    assert published.annotations.title == "Ask the Chief"


async def test_title_given_only_in_annotations_is_promoted_to_the_tool_title():
    """One setting, two protocol slots -- whichever the developer wrote fills both."""
    agent = _agent()
    os = AgentOS(
        agents=[agent],
        mcp=MCPConfig(default_tools=False, tools=[agent.as_tool(annotations={"title": "Legacy Slot"})]),
    )

    published = await _tool_by_name(os, "chief")

    assert published.title == "Legacy Slot"
    assert published.annotations.title == "Legacy Slot"


async def test_the_explicit_title_wins_when_both_slots_are_set():
    """Both slots are one setting, so their tie-break is real API surface: the tool's
    own title field is the one a developer means."""
    agent = _agent()
    os = AgentOS(
        agents=[agent],
        mcp=MCPConfig(
            default_tools=False,
            tools=[agent.as_tool(title="Ask the Chief", annotations={"title": "Legacy Slot"})],
        ),
    )

    published = await _tool_by_name(os, "chief")

    assert published.title == "Ask the Chief"
    assert published.annotations.title == "Ask the Chief"


async def test_remote_with_overrides_and_no_title_still_skips_the_metadata_fetch(monkeypatch):
    """A remote's name is a network-backed property that blocks to the timeout when the
    remote is unreachable. Filling a DISPLAY TITLE must never be the thing that triggers
    that read: the tool name is the fallback instead."""
    from agno.team.remote import RemoteTeam

    def _boom(component):
        raise AssertionError("metadata was fetched just to fill a title")

    monkeypatch.setattr(mcp_mod, "_safe_component_metadata", _boom)
    remote = RemoteTeam(base_url="http://127.0.0.1:9", team_id="remote-team")
    os = AgentOS(
        teams=[remote],
        mcp=MCPConfig(
            default_tools=False,
            tools=[remote.as_tool(name="ask_remote", description="Ask the remote team.")],
        ),
    )

    published = await _tool_by_name(os, "ask_remote")

    assert published.title == "ask_remote"


# --------------------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------------------


def test_misspelled_annotation_is_refused_with_a_suggestion():
    """ToolAnnotations accepts unknown keys, so an unchecked typo reaches a reviewing
    client as "no such annotation" -- a listing rejection discovered at review time."""
    with pytest.raises(ValueError) as excinfo:
        _agent().as_tool(annotations={"readonlyHint": True})

    message = str(excinfo.value)
    assert "readonlyHint" in message
    assert "'readOnlyHint'" in message


def test_unknown_annotation_without_a_close_match_still_lists_the_valid_keys():
    with pytest.raises(ValueError) as excinfo:
        _agent().as_tool(annotations={"totallyMadeUp": True})

    assert "readOnlyHint" in str(excinfo.value)


def test_non_bool_hint_is_refused():
    with pytest.raises(TypeError) as excinfo:
        _agent().as_tool(annotations={"readOnlyHint": "yes"})

    assert "readOnlyHint" in str(excinfo.value)


def test_non_string_title_annotation_is_refused():
    with pytest.raises(TypeError):
        _agent().as_tool(annotations={"title": 42})


def test_the_valid_key_list_matches_the_installed_protocol_model():
    """The allowlist is a copy of the protocol's own field set. If an SDK bump adds a
    hint, this fails here rather than rejecting a developer's valid annotation."""
    from mcp.types import ToolAnnotations

    from agno.tools.annotations import TOOL_ANNOTATION_KEYS

    assert set(TOOL_ANNOTATION_KEYS) == set(ToolAnnotations.model_fields)


def test_validation_stores_a_copy_so_a_later_edit_cannot_smuggle_a_key_in():
    """The marker is frozen, but a dict field is not: keeping the caller's own dict
    would let an edit after construction put an unchecked key on a validated marker."""
    developer_dict = {"readOnlyHint": True}
    marker = _agent().as_tool(annotations=developer_dict)

    developer_dict["readonlyHint"] = True

    assert marker.annotations == {"readOnlyHint": True}


def test_function_validates_its_annotations_too():
    with pytest.raises(ValueError):
        Function(name="f", annotations={"readonlyHint": True})


def test_tool_decorator_accepts_title_and_annotations():
    @tool(title="Weather Lookup", annotations={"readOnlyHint": True})
    def get_weather(city: str) -> str:
        """Look up the weather."""
        return "sunny"

    assert get_weather.title == "Weather Lookup"
    assert get_weather.annotations == {"readOnlyHint": True}


# --------------------------------------------------------------------------------------
# Custom tools
# --------------------------------------------------------------------------------------


async def test_toolkit_method_publishes_the_metadata_its_decorator_declared():
    """A Toolkit rebuilds each decorated method into a fresh Function, so presentation
    has to survive that rebuild -- otherwise the same @tool arguments publish annotations
    from a module-level function and nothing from a toolkit method."""
    from agno.tools.toolkit import Toolkit

    class WeatherKit(Toolkit):
        def __init__(self):
            super().__init__(name="weather", tools=[self.get_weather])

        @tool(title="Weather Lookup", annotations={"readOnlyHint": True, "openWorldHint": True})
        def get_weather(self, city: str) -> str:
            """Look up the weather."""
            return "sunny"

    kit = WeatherKit()
    os = AgentOS(agents=[_agent()], mcp=MCPConfig(default_tools=False, tools=[kit.functions["get_weather"]]))

    published = await _tool_by_name(os, "get_weather")

    assert published.title == "Weather Lookup"
    assert published.annotations.readOnlyHint is True
    assert published.annotations.openWorldHint is True


def test_presentation_survives_a_registry_reload():
    """to_dict() deliberately omits presentation, so the registry restores it from the
    live Function instead -- a reloaded component must publish the same title and hints
    a fresh one does."""
    from agno.tools.function import RUNTIME_ONLY_FIELDS, SERIALIZED_FIELDS

    unaccounted = set(Function.model_fields) - set(SERIALIZED_FIELDS) - set(RUNTIME_ONLY_FIELDS)

    assert "title" not in unaccounted
    assert "annotations" not in unaccounted


async def test_custom_tool_publishes_its_title_and_annotations():
    @tool(title="Weather Lookup", annotations={"readOnlyHint": True, "openWorldHint": True})
    def get_weather(city: str) -> str:
        """Look up the weather."""
        return "sunny"

    os = AgentOS(agents=[_agent()], mcp=MCPConfig(default_tools=False, tools=[get_weather]))

    published = await _tool_by_name(os, "get_weather")

    assert published.title == "Weather Lookup"
    assert published.annotations.title == "Weather Lookup"
    assert published.annotations.readOnlyHint is True
    assert published.annotations.openWorldHint is True


async def test_custom_tool_title_given_only_in_annotations_is_promoted():
    """The same one-setting-two-slots rule the exposed path follows."""

    @tool(annotations={"title": "Legacy Slot", "readOnlyHint": True})
    def legacy(city: str) -> str:
        """Title set via annotations only."""
        return "x"

    os = AgentOS(agents=[_agent()], mcp=MCPConfig(default_tools=False, tools=[legacy]))

    published = await _tool_by_name(os, "legacy")

    assert published.title == "Legacy Slot"
    assert published.annotations.title == "Legacy Slot"


async def test_plain_callable_registers_without_annotations():
    """No metadata is invented for a bare callable, and nothing crashes for the lack
    of it."""

    def ping() -> str:
        """Ping."""
        return "pong"

    os = AgentOS(agents=[_agent()], mcp=MCPConfig(default_tools=False, tools=[ping]))

    published = await _tool_by_name(os, "ping")

    assert published.annotations is None


async def test_presentation_is_never_duck_typed_off_a_non_function_tool():
    """A stray ``.annotations`` attribute on some other tool-shaped object means
    something else entirely; only an Agno Function publishes annotations."""

    class ToolLike:
        name = "look_alike"
        description = "Not an Agno Function."
        title = "Should Not Be Used"
        annotations = {"readOnlyHint": True}

        @staticmethod
        def entrypoint() -> str:
            return "x"

    os = AgentOS(agents=[_agent()], mcp=MCPConfig(default_tools=False, tools=[ToolLike()]))

    published = await _tool_by_name(os, "look_alike")

    assert published.title is None
    assert published.annotations is None


# --------------------------------------------------------------------------------------
# Built-ins
# --------------------------------------------------------------------------------------


# What each built-in claims about itself, as (readOnlyHint, destructiveHint). A wrong
# hint is worse than a missing one -- a reviewer tests these against real behaviour --
# so the values are pinned per tool, not just checked for presence.
_BUILTIN_HINTS = {
    "get_agentos_config": (True, None),
    "run_agent": (False, True),
    "run_team": (False, True),
    "run_workflow": (False, True),
    "continue_run": (False, True),
    "cancel_run": (False, True),
    "get_sessions": (True, None),
    "get_session_runs": (True, None),
}


async def test_every_builtin_tool_publishes_the_hints_it_claims():
    """The bar a listing review applies to a customer's tools, applied to our own."""
    os = AgentOS(agents=[_agent()], mcp=MCPConfig())

    published = await _tools_by_name(os)

    assert set(published) == set(mcp_mod._BUILTIN_TOOL_NAMES) == set(_BUILTIN_HINTS)
    for name, entry in published.items():
        read_only, destructive = _BUILTIN_HINTS[name]
        assert entry.title, f"{name} has no title"
        assert entry.description, f"{name} has no description"
        assert entry.annotations is not None, f"{name} has no annotations"
        assert entry.annotations.readOnlyHint is read_only, f"{name} readOnlyHint changed"
        assert entry.annotations.destructiveHint is destructive, f"{name} destructiveHint changed"
        # A tool that is not read-only must say whether its write destroys something,
        # rather than leaving a client to fall back on the protocol default (true).
        if entry.annotations.readOnlyHint is False:
            assert entry.annotations.destructiveHint is not None, f"{name} writes but omits destructiveHint"
        assert entry.annotations.title == entry.title, f"{name} title not mirrored into annotations"


# --------------------------------------------------------------------------------------
# The marker, and what the model sees
# --------------------------------------------------------------------------------------


def test_component_tool_carries_the_new_fields_and_stays_frozen():
    from dataclasses import FrozenInstanceError

    from agno.tools import ComponentTool

    marker = _agent().as_tool(name="ask", description="d", title="Ask", annotations={"readOnlyHint": True})

    assert isinstance(marker, ComponentTool)
    assert (marker.name, marker.description, marker.title) == ("ask", "d", "Ask")
    assert marker.annotations == {"readOnlyHint": True}
    with pytest.raises(FrozenInstanceError):
        marker.title = "Renamed"  # type: ignore[misc]


def test_presentation_fields_never_reach_the_model_facing_schema():
    """title/annotations are for people and clients, not for the model: to_dict() feeds
    the tool definition sent to the provider and serializes an explicit allowlist."""
    fn = Function(name="f", description="d", title="Display Name", annotations={"readOnlyHint": True})

    serialized = fn.to_dict()

    assert "title" not in serialized
    assert "annotations" not in serialized
