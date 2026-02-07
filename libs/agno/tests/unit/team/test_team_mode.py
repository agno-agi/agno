"""Unit tests for TeamMode enum and backwards compatibility."""

import pytest

from agno.team.mode import TeamMode


class TestTeamMode:
    """Tests for TeamMode enum values and behavior."""

    def test_enum_values(self):
        assert TeamMode.coordinate == "coordinate"
        assert TeamMode.route == "route"
        assert TeamMode.broadcast == "broadcast"
        assert TeamMode.tasks == "tasks"

    def test_from_string(self):
        assert TeamMode("coordinate") == TeamMode.coordinate
        assert TeamMode("route") == TeamMode.route
        assert TeamMode("broadcast") == TeamMode.broadcast
        assert TeamMode("tasks") == TeamMode.tasks

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError):
            TeamMode("invalid")

    def test_is_str_subclass(self):
        assert isinstance(TeamMode.coordinate, str)


class TestTeamModeBackwardsCompat:
    """Tests that mode inference from legacy booleans works correctly."""

    def test_default_mode_is_coordinate(self):
        """When no mode or booleans are set, mode should be coordinate."""
        from agno.team.team import Team

        team = Team(name="test", members=[])
        assert team.mode == TeamMode.coordinate
        assert not team.respond_directly
        assert not team.delegate_to_all_members

    def test_mode_coordinate_explicit(self):
        from agno.team.team import Team

        team = Team(name="test", members=[], mode=TeamMode.coordinate)
        assert team.mode == TeamMode.coordinate

    def test_mode_route_sets_respond_directly(self):
        from agno.team.team import Team

        team = Team(name="test", members=[], mode=TeamMode.route)
        assert team.mode == TeamMode.route
        assert team.respond_directly is True

    def test_mode_broadcast_sets_delegate_to_all(self):
        from agno.team.team import Team

        team = Team(name="test", members=[], mode=TeamMode.broadcast)
        assert team.mode == TeamMode.broadcast
        assert team.delegate_to_all_members is True

    def test_mode_tasks(self):
        from agno.team.team import Team

        team = Team(name="test", members=[], mode=TeamMode.tasks)
        assert team.mode == TeamMode.tasks

    def test_respond_directly_infers_route(self):
        """Legacy boolean should set mode to route."""
        from agno.team.team import Team

        team = Team(name="test", members=[], respond_directly=True)
        assert team.mode == TeamMode.route

    def test_delegate_to_all_infers_broadcast(self):
        """Legacy boolean should set mode to broadcast."""
        from agno.team.team import Team

        team = Team(name="test", members=[], delegate_to_all_members=True)
        assert team.mode == TeamMode.broadcast

    def test_mode_route_overrides_conflicting_delegate_to_all(self):
        """Explicit mode=route should force delegate_to_all_members=False even if passed True."""
        from agno.team.team import Team

        team = Team(name="test", members=[], mode=TeamMode.route, delegate_to_all_members=True)
        assert team.mode == TeamMode.route
        assert team.respond_directly is True
        assert team.delegate_to_all_members is False

    def test_mode_broadcast_overrides_conflicting_respond_directly(self):
        """Explicit mode=broadcast should force respond_directly=False even if passed True."""
        from agno.team.team import Team

        team = Team(name="test", members=[], mode=TeamMode.broadcast, respond_directly=True)
        assert team.mode == TeamMode.broadcast
        assert team.delegate_to_all_members is True
        assert team.respond_directly is False

    def test_mode_coordinate_overrides_conflicting_booleans(self):
        """Explicit mode=coordinate should force both booleans False."""
        from agno.team.team import Team

        team = Team(name="test", members=[], mode=TeamMode.coordinate, respond_directly=True, delegate_to_all_members=True)
        assert team.mode == TeamMode.coordinate
        assert team.respond_directly is False
        assert team.delegate_to_all_members is False

    def test_mode_tasks_overrides_conflicting_booleans(self):
        """Explicit mode=tasks should force both booleans False."""
        from agno.team.team import Team

        team = Team(name="test", members=[], mode=TeamMode.tasks, respond_directly=True, delegate_to_all_members=True)
        assert team.mode == TeamMode.tasks
        assert team.respond_directly is False
        assert team.delegate_to_all_members is False

    def test_max_iterations_default(self):
        from agno.team.team import Team

        team = Team(name="test", members=[])
        assert team.max_iterations == 10

    def test_max_iterations_custom(self):
        from agno.team.team import Team

        team = Team(name="test", members=[], max_iterations=25)
        assert team.max_iterations == 25
