"""
Unit tests for Team trait composition.

Tests cover:
- MRO method collision detection across traits
- deep_copy() isolation guarantees
- Import compatibility for public API surface
- to_dict/from_dict round-trip for trait-split fields
"""

from __future__ import annotations

from typing import Dict, List

import pytest

from agno.agent.agent import Agent
from agno.team.team import Team
from agno.team.trait.base import TeamTraitBase


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def basic_team():
    return Team(id="test-team", name="Test Team", members=[])


@pytest.fixture
def team_with_agents():
    a1 = Agent(id="agent-1", name="Agent One", role="Helper")
    a2 = Agent(id="agent-2", name="Agent Two", role="Researcher")
    return Team(id="team-agents", name="Agent Team", members=[a1, a2])


@pytest.fixture
def team_with_state():
    return Team(
        id="state-team",
        name="State Team",
        session_state={"counter": 0, "items": ["a", "b"]},
        metadata={"env": "test"},
        instructions=["Be helpful", "Be concise"],
        members=[],
    )


@pytest.fixture
def nested_team():
    inner = Team(id="inner-team", name="Inner Team", members=[])
    agent = Agent(id="outer-agent", name="Outer Agent")
    return Team(id="outer-team", name="Outer Team", members=[inner, agent])


# =============================================================================
# MRO Collision Detection
# =============================================================================


class TestMROCollisions:
    """Verify that no two traits accidentally define the same public method."""

    # Traits that compose Team (in MRO order)
    TRAIT_CLASSES: List[type] = []

    @classmethod
    def setup_class(cls):
        """Collect all trait classes from Team's MRO."""
        cls.TRAIT_CLASSES = [
            klass
            for klass in Team.__mro__
            if klass is not Team
            and klass is not TeamTraitBase
            and klass is not object
            and issubclass(klass, TeamTraitBase)
        ]

    def test_all_traits_are_present(self):
        """Ensure all expected traits are in the MRO."""
        trait_names = {c.__name__ for c in self.TRAIT_CLASSES}
        expected = {
            "TeamInitTrait",
            "TeamRunTrait",
            "TeamHooksTrait",
            "TeamToolsTrait",
            "TeamStorageTrait",
            "TeamMessagesTrait",
            "TeamResponseTrait",
            "TeamApiTrait",
            "TeamTelemetryTrait",
        }
        assert expected == trait_names

    def test_no_public_method_collisions(self):
        """No public method should be defined in more than one trait."""
        method_owners: Dict[str, List[str]] = {}
        for trait_cls in self.TRAIT_CLASSES:
            for name in trait_cls.__dict__:
                if name.startswith("__"):
                    continue
                if callable(getattr(trait_cls, name, None)) or isinstance(
                    getattr(trait_cls, name, None), (classmethod, staticmethod, property)
                ):
                    method_owners.setdefault(name, []).append(trait_cls.__name__)

        collisions = {name: owners for name, owners in method_owners.items() if len(owners) > 1}
        assert collisions == {}, f"Method collisions detected across traits: {collisions}"

    def test_no_private_method_collisions(self):
        """No _single_underscore method should be defined in more than one trait."""
        method_owners: Dict[str, List[str]] = {}
        for trait_cls in self.TRAIT_CLASSES:
            for name in trait_cls.__dict__:
                if name.startswith("__"):
                    continue
                if name.startswith("_") and callable(getattr(trait_cls, name, None)):
                    method_owners.setdefault(name, []).append(trait_cls.__name__)

        collisions = {name: owners for name, owners in method_owners.items() if len(owners) > 1}
        assert collisions == {}, f"Private method collisions detected across traits: {collisions}"

    def test_trait_base_attributes_cover_all_dataclass_fields(self):
        """TeamTraitBase should declare all public fields used by Team dataclass."""
        from dataclasses import fields as dc_fields

        team_field_names = {f.name for f in dc_fields(Team) if not f.name.startswith("_")}
        # Use __annotations__ since base attributes are type-only declarations (no assigned values)
        base_attrs = set(TeamTraitBase.__annotations__.keys())

        missing = team_field_names - base_attrs
        # Some fields may be intentionally excluded from the base
        # This test alerts us if new fields are added to Team but not to TeamTraitBase
        if missing:
            pytest.fail(f"TeamTraitBase is missing declarations for Team fields: {missing}")


# =============================================================================
# deep_copy() Tests
# =============================================================================


class TestDeepCopy:
    """Tests for Team.deep_copy() method."""

    def test_deep_copy_returns_new_instance(self, basic_team):
        """deep_copy returns a different object."""
        copy = basic_team.deep_copy()
        assert copy is not basic_team
        assert copy.id == basic_team.id
        assert copy.name == basic_team.name

    def test_deep_copy_isolates_session_state(self, team_with_state):
        """Mutating session_state on the copy doesn't affect the original."""
        copy = team_with_state.deep_copy()
        copy.session_state["counter"] = 999
        copy.session_state["items"].append("c")

        assert team_with_state.session_state["counter"] == 0
        assert team_with_state.session_state["items"] == ["a", "b"]

    def test_deep_copy_isolates_metadata(self, team_with_state):
        """Mutating metadata on the copy doesn't affect the original."""
        copy = team_with_state.deep_copy()
        copy.metadata["env"] = "production"

        assert team_with_state.metadata["env"] == "test"

    def test_deep_copy_isolates_members(self, team_with_agents):
        """Members list should be independent."""
        copy = team_with_agents.deep_copy()

        # Lists should be independent
        assert copy.members is not team_with_agents.members
        assert len(copy.members) == len(team_with_agents.members)

        # Individual agents should be copies (not same object)
        for orig, copied in zip(team_with_agents.members, copy.members):
            assert copied is not orig
            assert copied.id == orig.id

    def test_deep_copy_with_update(self, basic_team):
        """deep_copy(update=...) applies field overrides."""
        copy = basic_team.deep_copy(update={"name": "Updated Team", "description": "New description"})

        assert copy.name == "Updated Team"
        assert copy.description == "New description"
        assert basic_team.name == "Test Team"
        assert basic_team.description is None

    def test_deep_copy_nested_team(self, nested_team):
        """deep_copy should recursively copy nested team members."""
        copy = nested_team.deep_copy()

        assert copy is not nested_team
        assert len(copy.members) == 2

        # Inner team should be a copy
        inner_copy = copy.members[0]
        inner_orig = nested_team.members[0]
        assert inner_copy is not inner_orig
        assert inner_copy.id == inner_orig.id

    def test_deep_copy_preserves_instructions(self, team_with_state):
        """deep_copy preserves instructions as an independent copy."""
        copy = team_with_state.deep_copy()

        assert copy.instructions == team_with_state.instructions
        # Mutating the copy's instructions shouldn't affect original
        if isinstance(copy.instructions, list):
            copy.instructions.append("Extra instruction")
            assert len(team_with_state.instructions) == 2


# =============================================================================
# Import Compatibility
# =============================================================================


class TestImportCompatibility:
    """Ensure the public API surface is accessible from expected import paths."""

    def test_team_importable_from_agno_team(self):
        """from agno.team import Team should work."""
        from agno.team import Team as TeamFromPackage

        assert TeamFromPackage is Team

    def test_team_importable_from_agno_team_team(self):
        """from agno.team.team import Team should work."""
        from agno.team.team import Team as TeamFromModule

        assert TeamFromModule is Team

    def test_run_types_reexported_from_team_team(self):
        """TeamRunOutput and related types should be importable from agno.team.team."""
        from agno.run.team import TeamRunEvent as Canonical
        from agno.team.team import TeamRunEvent

        assert TeamRunEvent is Canonical

    def test_run_output_reexported(self):
        from agno.run.team import TeamRunOutput as Canonical
        from agno.team.team import TeamRunOutput

        assert TeamRunOutput is Canonical

    def test_module_helpers_importable(self):
        """get_team_by_id and get_teams should be importable from agno.team."""
        from agno.team import get_team_by_id, get_teams

        assert callable(get_team_by_id)
        assert callable(get_teams)

    def test_event_types_importable_from_package(self):
        """All event types should be importable from agno.team."""
        from agno.team import (
            MemoryUpdateCompletedEvent,
            MemoryUpdateStartedEvent,
            ReasoningCompletedEvent,
            ReasoningStartedEvent,
            ReasoningStepEvent,
            RunCancelledEvent,
            RunCompletedEvent,
            RunContentEvent,
            RunErrorEvent,
            RunStartedEvent,
            TeamRunEvent,
            TeamRunOutput,
            TeamRunOutputEvent,
            ToolCallCompletedEvent,
            ToolCallStartedEvent,
        )

        # Just verify they're all non-None class references
        for cls in [
            MemoryUpdateCompletedEvent,
            MemoryUpdateStartedEvent,
            ReasoningCompletedEvent,
            ReasoningStartedEvent,
            ReasoningStepEvent,
            RunCancelledEvent,
            RunCompletedEvent,
            RunContentEvent,
            RunErrorEvent,
            RunStartedEvent,
            TeamRunEvent,
            TeamRunOutput,
            TeamRunOutputEvent,
            ToolCallCompletedEvent,
            ToolCallStartedEvent,
        ]:
            assert cls is not None

    def test_remote_team_importable(self):
        """RemoteTeam should be importable from agno.team."""
        from agno.team import RemoteTeam

        assert RemoteTeam is not None


# =============================================================================
# to_dict / from_dict Round-Trip (Trait-Split Fields)
# =============================================================================


class TestRoundTripTraitFields:
    """Test round-trip for fields that span multiple traits after the split."""

    def test_roundtrip_context_flags(self):
        """Context flags (from MessagesTrait) survive round-trip."""
        team = Team(
            id="ctx-team",
            add_datetime_to_context=True,
            add_location_to_context=True,
            add_name_to_context=True,
            markdown=True,
            members=[],
        )
        config = team.to_dict()
        restored = Team.from_dict(config)

        assert restored.add_datetime_to_context is True
        assert restored.add_location_to_context is True
        assert restored.add_name_to_context is True
        assert restored.markdown is True

    def test_roundtrip_storage_flags(self):
        """Storage flags (from StorageTrait) survive round-trip."""
        team = Team(
            id="storage-team",
            store_media=False,
            store_tool_messages=False,
            store_history_messages=False,
            store_member_responses=True,
            store_events=True,
            cache_session=True,
            members=[],
        )
        config = team.to_dict()
        restored = Team.from_dict(config)

        assert restored.store_media is False
        assert restored.store_tool_messages is False
        assert restored.store_history_messages is False
        assert restored.store_member_responses is True
        assert restored.store_events is True
        assert restored.cache_session is True

    def test_roundtrip_run_settings(self):
        """Run settings (from RunTrait) survive round-trip."""
        team = Team(
            id="run-team",
            retries=3,
            delay_between_retries=2,
            exponential_backoff=True,
            stream=True,
            stream_events=True,
            members=[],
        )
        config = team.to_dict()
        restored = Team.from_dict(config)

        assert restored.retries == 3
        assert restored.delay_between_retries == 2
        assert restored.exponential_backoff is True
        assert restored.stream is True
        assert restored.stream_events is True

    def test_roundtrip_history_settings(self):
        """History settings survive round-trip."""
        # Note: num_history_runs and num_history_messages are mutually exclusive
        team = Team(
            id="history-team",
            add_history_to_context=True,
            num_history_runs=5,
            max_tool_calls_from_history=3,
            members=[],
        )
        config = team.to_dict()
        restored = Team.from_dict(config)

        assert restored.add_history_to_context is True
        assert restored.num_history_runs == 5
        assert restored.max_tool_calls_from_history == 3

    def test_roundtrip_reasoning_settings(self):
        """Reasoning settings survive round-trip."""
        team = Team(
            id="reasoning-team",
            reasoning=True,
            reasoning_min_steps=2,
            reasoning_max_steps=15,
            members=[],
        )
        config = team.to_dict()
        restored = Team.from_dict(config)

        assert restored.reasoning is True
        assert restored.reasoning_min_steps == 2
        assert restored.reasoning_max_steps == 15

    def test_roundtrip_preserves_session_state(self):
        """session_state dict survives round-trip."""
        team = Team(
            id="session-team",
            session_state={"user_pref": "dark", "count": 42},
            members=[],
        )
        config = team.to_dict()
        restored = Team.from_dict(config)

        assert restored.session_state == {"user_pref": "dark", "count": 42}

    def test_roundtrip_minimal_team(self):
        """A minimal team (just id) round-trips cleanly."""
        team = Team(id="minimal", members=[])
        config = team.to_dict()
        restored = Team.from_dict(config)

        assert restored.id == "minimal"
