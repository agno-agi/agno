"""The declared/folded contract behind the Studio build palette.

``Registry.add_tool`` records how a tool arrived and ``Registry.undeclared_tool_names``
is the set the palette policy reads. The contract these tests pin:

- a tool the deployer declares is buildable, whether the declaration arrives
  before or after the AgentOS fold, and whether or not it dedupes against the
  folded instance;
- a merely folded tool stays resolvable but not buildable;
- foldedness is a property of the NAME (the palette selects by name), so a
  same-named toolkit carrying a different function set cannot take a declared
  name out of the palette.
"""

import json
from functools import partial
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.registry.registry import Registry, ToolSource
from agno.tools.calculator import CalculatorTools
from agno.tools.function import Function
from agno.tools.studio import StudioTools
from agno.tools.toolkit import Toolkit


def sample_search(query: str) -> str:
    """Search the web."""
    return query


def other_search(query: str) -> str:
    """Search the web, differently."""
    return query


def search_kit() -> Toolkit:
    return Toolkit(name="search_kit", tools=[sample_search])


@pytest.fixture
def db(tmp_path):
    return SqliteDb(id="tool-source-db", db_file=str(tmp_path / "tool_source.db"))


def _data(result: str) -> Dict[str, Any]:
    out = json.loads(result)
    assert out.get("ok") is True, out
    return out["data"]


def _error(result: str) -> Dict[str, Any]:
    out = json.loads(result)
    assert out.get("ok") is False, out
    return out["error"]


def _tool_rows(studio: StudioTools):
    return _data(studio.list_tools())["tools"]


class TestDeclarationWinsOverFold:
    """A declaration puts the name in the palette, in either order."""

    def test_declaring_an_equivalent_toolkit_after_the_fold_unfolds_the_name(self):
        # The common case: DuckDuckGoTools() written on the agent and again on
        # the registry. The declaration dedupes structurally and used to return
        # before the source was read.
        registry = Registry()
        registry.add_tool(search_kit(), source=ToolSource.DISCOVERED)
        assert registry.undeclared_tool_names == {"search_kit"}

        registry.add_tool(search_kit())

        assert registry.undeclared_tool_names == set()
        assert len(registry.tools) == 1

    def test_declaring_the_folded_instance_itself_unfolds_the_name(self):
        # The identity dedup branch: the deployer declares the very object the
        # fold already added.
        registry = Registry()
        toolkit = search_kit()
        registry.add_tool(toolkit, source=ToolSource.DISCOVERED)

        registry.add_tool(toolkit)

        assert registry.undeclared_tool_names == set()

    def test_declaring_a_folded_callable_unfolds_the_name(self):
        # Plain callables dedupe by equality, a second early return.
        registry = Registry()
        registry.add_tool(sample_search, source=ToolSource.DISCOVERED)
        assert registry.undeclared_tool_names == {"sample_search"}

        registry.add_tool(sample_search)

        assert registry.undeclared_tool_names == set()

    def test_declaring_a_folded_function_unfolds_the_name(self):
        registry = Registry()
        function = Function.from_callable(sample_search)
        registry.add_tool(function, source=ToolSource.DISCOVERED)
        assert registry.undeclared_tool_names == {"sample_search"}

        registry.add_tool(function)

        assert registry.undeclared_tool_names == set()

    def test_declaring_a_same_named_toolkit_with_a_different_function_set(self):
        # No dedup here: the two toolkits differ structurally, so both are kept.
        # The declared name is still buildable.
        registry = Registry()
        registry.add_tool(Toolkit(name="search_kit", tools=[other_search]), source=ToolSource.DISCOVERED)

        registry.add_tool(search_kit())

        assert registry.undeclared_tool_names == set()
        assert len(registry.tools) == 2

    def test_folding_a_same_named_toolkit_does_not_unlist_a_declaration(self):
        # The reverse order, and the shape the palette hit in practice: a
        # registered component carries a narrower toolkit of the same name.
        registry = Registry(tools=[CalculatorTools()])
        registry.add_tool(CalculatorTools(include_tools=["add", "subtract"]), source=ToolSource.DISCOVERED)

        assert registry.undeclared_tool_names == set()
        assert len(registry.tools) == 2

    def test_declaration_then_fold_stays_declared(self):
        registry = Registry()
        registry.add_tool(search_kit())
        registry.add_tool(search_kit(), source=ToolSource.DISCOVERED)

        assert registry.undeclared_tool_names == set()

    def test_legacy_string_sources_decide_the_same_way_on_the_dedup_path(self):
        registry = Registry()
        registry.add_tool(search_kit(), source="discovered")
        assert registry.undeclared_tool_names == {"search_kit"}

        registry.add_tool(search_kit(), source="declared")

        assert registry.undeclared_tool_names == set()

    def test_a_fold_after_a_declaration_does_not_refold(self):
        # Repeated folds (AgentOS.resync walks every component again) must not
        # undo the declaration.
        registry = Registry()
        registry.add_tool(search_kit(), source=ToolSource.DISCOVERED)
        registry.add_tool(search_kit())

        for _ in range(3):
            registry.add_tool(search_kit(), source=ToolSource.DISCOVERED)

        assert registry.undeclared_tool_names == set()


class TestDiscoveryNeverUnsetsADeclaration:
    """The other half of the contract: nothing here may open the palette."""

    def test_a_folded_toolkit_is_folded(self):
        registry = Registry()
        registry.add_tool(search_kit(), source=ToolSource.DISCOVERED)

        assert registry.undeclared_tool_names == {"search_kit"}

    def test_two_distinct_folded_toolkits_sharing_a_name_stay_folded(self):
        # Two components carry different toolkits under one name. Neither was
        # declared, so the name stays out of the palette.
        registry = Registry()
        registry.add_tool(Toolkit(name="search_kit", tools=[sample_search]), source=ToolSource.DISCOVERED)
        registry.add_tool(Toolkit(name="search_kit", tools=[other_search]), source=ToolSource.DISCOVERED)

        assert registry.undeclared_tool_names == {"search_kit"}

    def test_three_distinct_folded_toolkits_sharing_a_name_stay_folded(self):
        registry = Registry()
        registry.add_tool(Toolkit(name="search_kit", tools=[sample_search]), source=ToolSource.DISCOVERED)
        registry.add_tool(Toolkit(name="search_kit", tools=[other_search]), source=ToolSource.DISCOVERED)
        registry.add_tool(Toolkit(name="search_kit", tools=[sample_search, other_search]), source=ToolSource.DISCOVERED)

        assert registry.undeclared_tool_names == {"search_kit"}
        assert len(registry.tools) == 3

    def test_an_unrecognised_source_changes_nothing(self):
        # Only the two known sources decide. A value that is neither leaves the
        # standing answer alone, so a source added later cannot open the
        # palette by accident.
        registry = Registry()
        registry.add_tool(search_kit(), source=ToolSource.DISCOVERED)

        registry.add_tool(Toolkit(name="search_kit", tools=[other_search]), source="mirrored")

        assert registry.undeclared_tool_names == {"search_kit"}
        assert len(registry.tools) == 2

    def test_a_discovered_callable_sharing_a_discovered_toolkits_name_stays_undeclared(self):
        registry = Registry()
        registry.add_tool(Toolkit(name="sample_search", tools=[other_search]), source=ToolSource.DISCOVERED)
        registry.add_tool(sample_search, source=ToolSource.DISCOVERED)

        assert registry.undeclared_tool_names == {"sample_search"}

    def test_repeated_folds_of_the_same_toolkit_stay_folded(self):
        registry = Registry()
        for _ in range(3):
            registry.add_tool(search_kit(), source=ToolSource.DISCOVERED)

        assert registry.undeclared_tool_names == {"search_kit"}
        assert len(registry.tools) == 1

    def test_a_tool_without_a_usable_name_is_never_marked(self):
        # A partial has neither name nor __name__; it cannot be selected by
        # name, so there is nothing to mark or clear.
        registry = Registry()
        registry.add_tool(partial(sample_search, "q"), source=ToolSource.DISCOVERED)

        assert registry.undeclared_tool_names == set()

    def test_a_non_string_name_is_not_marked(self):
        registry = Registry()
        tool = MagicMock()
        tool.name = object()
        registry.add_tool(tool, source=ToolSource.DISCOVERED)

        assert registry.undeclared_tool_names == set()


class TestPaletteReadsTheDeclaration:
    """The three palette readers, driven read-only against the registry."""

    def test_a_redeclared_toolkit_is_buildable_and_listed_declared(self, db):
        registry = Registry(models=[OpenAIResponses(id="gpt-5.5")], dbs=[db])
        registry.add_tool(search_kit(), source=ToolSource.DISCOVERED)
        registry.add_tool(search_kit())

        studio = StudioTools(registry=registry, db=db)

        assert studio._buildable_tool("search_kit") is True
        # A member requested by its bare function name is judged by the owning
        # toolkit's policy, so it flips with it.
        assert studio._buildable_tool("sample_search") is True
        rows = _tool_rows(studio)
        assert [(row["name"], row["buildable"], row["source"]) for row in rows] == [("search_kit", True, "declared")]

    def test_creating_an_agent_with_a_redeclared_toolkit_succeeds(self, db):
        registry = Registry(models=[OpenAIResponses(id="gpt-5.5")], dbs=[db])
        registry.add_tool(search_kit(), source=ToolSource.DISCOVERED)
        registry.add_tool(search_kit())

        studio = StudioTools(registry=registry, db=db)

        assert (
            _data(studio.create_agent(name="builder", instructions="i", tool_names=["search_kit"]))["id"] == "builder"
        )

    def test_a_folded_toolkit_alone_is_still_refused(self, db):
        registry = Registry(models=[OpenAIResponses(id="gpt-5.5")], dbs=[db])
        registry.add_tool(search_kit(), source=ToolSource.DISCOVERED)

        studio = StudioTools(registry=registry, db=db)

        assert studio._buildable_tool("search_kit") is False
        error = _error(studio.create_agent(name="x", instructions="i", tool_names=["search_kit"]))
        assert error["code"] == "tool_not_allowed"

    def test_a_same_named_collision_is_not_reported_as_a_palette_denial(self, db):
        # Both toolkits are named "calculator" but only one was declared. The
        # palette lists the name as buildable; the refusal that remains is the
        # honest one - two registry entries answer to the name, so selecting by
        # name is ambiguous - not "allow-list a tool you already declared".
        registry = Registry(tools=[CalculatorTools()], models=[OpenAIResponses(id="gpt-5.5")], dbs=[db])
        registry.add_tool(CalculatorTools(include_tools=["add", "subtract"]), source=ToolSource.DISCOVERED)

        studio = StudioTools(registry=registry, db=db)

        assert studio._buildable_tool("calculator") is True
        assert all(row["buildable"] is True and row["source"] == "declared" for row in _tool_rows(studio))
        error = _error(studio.create_agent(name="x", instructions="i", tool_names=["calculator"]))
        assert error["code"] != "tool_not_allowed"

    def test_a_denial_still_wins_over_a_declaration(self, db):
        registry = Registry(models=[OpenAIResponses(id="gpt-5.5")], dbs=[db])
        registry.add_tool(search_kit(), source=ToolSource.DISCOVERED)
        registry.add_tool(search_kit())

        studio = StudioTools(registry=registry, db=db, denied_tools=["search_kit"])

        assert studio._buildable_tool("search_kit") is False


class TestAgentOSFold:
    """End to end: the AgentOS walk is the only thing that folds in practice."""

    def test_declaring_after_agentos_construction_makes_the_tool_buildable(self, db):
        from agno.os import AgentOS

        registry = Registry(models=[OpenAIResponses(id="gpt-5.5")], dbs=[db])
        agent = Agent(id="a1", name="A1", model=OpenAIResponses(id="gpt-5.5"), tools=[search_kit()])
        agent_os = AgentOS(agents=[agent], registry=registry, telemetry=False)
        assert registry.undeclared_tool_names == {"search_kit"}

        registry.add_tool(search_kit())

        studio = StudioTools(registry=registry, db=db)
        assert studio._buildable_tool("search_kit") is True
        assert _data(studio.create_agent(name="built", instructions="i", tool_names=["search_kit"]))["id"] == "built"

        # A resync walks every component again; the declaration survives it.
        agent_os.resync(agent_os.get_app())
        assert registry.undeclared_tool_names == set()
        assert studio._buildable_tool("search_kit") is True

    def test_an_undeclared_agent_toolkit_stays_out_of_the_palette(self, db):
        from agno.os import AgentOS

        registry = Registry(models=[OpenAIResponses(id="gpt-5.5")], dbs=[db])
        agent = Agent(id="a1", name="A1", model=OpenAIResponses(id="gpt-5.5"), tools=[search_kit()])
        AgentOS(agents=[agent], registry=registry, telemetry=False)

        studio = StudioTools(registry=registry, db=db)

        assert studio._buildable_tool("search_kit") is False


class TestMemoryManagerIdsForName:
    """The public accessor for the managers a listing name matches."""

    def _manager(self, manager_id, name=None):
        manager = MagicMock()
        manager.id = manager_id
        manager.name = name
        return manager

    def test_empty_registry_returns_no_ids(self):
        assert Registry().memory_manager_ids_for_name("shared") == []

    def test_a_none_manager_list_is_guarded(self):
        registry = Registry()
        registry.memory_managers = None  # type: ignore[assignment]

        assert registry.memory_manager_ids_for_name("shared") == []

    def test_every_manager_listed_under_the_name_is_returned_in_order(self):
        first = self._manager("mm-1", name="shared")
        second = self._manager("mm-2", name="shared")
        registry = Registry(memory_managers=[first, second, self._manager("mm-3", name="other")])

        assert registry.memory_manager_ids_for_name("shared") == ["mm-1", "mm-2"]

    def test_a_manager_without_a_name_is_listed_under_its_id(self):
        registry = Registry(memory_managers=[self._manager("mm-1")])

        assert registry.memory_manager_ids_for_name("mm-1") == ["mm-1"]

    def test_a_manager_without_an_id_is_skipped(self):
        registry = Registry(memory_managers=[self._manager(None, name="shared"), self._manager("mm-2", name="shared")])

        assert registry.memory_manager_ids_for_name("shared") == ["mm-2"]

    def test_an_unknown_name_returns_no_ids(self):
        registry = Registry(memory_managers=[self._manager("mm-1", name="shared")])

        assert registry.memory_manager_ids_for_name("missing") == []

    def test_it_agrees_with_the_ambiguity_predicate(self):
        registry = Registry(
            memory_managers=[self._manager("mm-1", name="shared"), self._manager("mm-2", name="shared")]
        )

        assert registry.memory_manager_name_is_ambiguous("shared") is True
        assert len(registry.memory_manager_ids_for_name("shared")) == 2
