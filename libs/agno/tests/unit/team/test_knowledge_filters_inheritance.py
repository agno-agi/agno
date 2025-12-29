"""Tests for Team knowledge_filters inheritance to member agents."""

from unittest.mock import MagicMock

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.utils.knowledge import get_agentic_or_user_search_filters


class TestGetAgenticOrUserSearchFilters:
    """Tests for the get_agentic_or_user_search_filters utility function."""

    def test_no_filters(self):
        """Test when no filters are provided."""
        result = get_agentic_or_user_search_filters(None, None)
        assert result == {}

    def test_agent_filters_only(self):
        """Test when only agent filters are provided."""
        agent_filters = {"type": "api", "version": "v1"}
        result = get_agentic_or_user_search_filters(agent_filters, None)
        assert result == agent_filters

    def test_effective_filters_only(self):
        """Test when only effective (user/team) filters are provided - this was the bug case."""
        effective_filters = {"category": "docs", "department": "research"}
        result = get_agentic_or_user_search_filters(None, effective_filters)
        assert result == effective_filters

    def test_both_filters_effective_wins(self):
        """Test when both filters are provided - effective filters should take priority."""
        agent_filters = {"type": "api"}
        effective_filters = {"category": "docs"}
        result = get_agentic_or_user_search_filters(agent_filters, effective_filters)
        assert result == effective_filters

    def test_effective_filters_list_raises_error(self):
        """Test that list-type effective_filters raises ValueError."""
        from agno.filters import FilterExpr

        # Create mock FilterExpr objects
        filter_list = [MagicMock(spec=FilterExpr)]
        with pytest.raises(ValueError, match="Merging dict and list of filters is not supported"):
            get_agentic_or_user_search_filters(None, filter_list)


class TestTeamKnowledgeFiltersInheritance:
    """Tests for Team knowledge_filters inheritance to member agents."""

    def _create_mock_knowledge(self):
        """Create a mock Knowledge object for testing."""
        return MagicMock()

    def test_inheritance_disabled_by_default(self):
        """Test that inheritance is disabled by default."""
        mock_kb = self._create_mock_knowledge()

        agent = Agent(
            name="Test Agent",
            role="Assistant",
            knowledge=mock_kb,
        )

        team = Team(
            name="Test Team",
            model=OpenAIChat(id="gpt-4o-mini"),
            members=[agent],
            knowledge=mock_kb,
            knowledge_filters={"department": "research"},
        )

        # Default should be False
        assert team.inherit_knowledge_filters_to_agents is False
        assert team.knowledge_filters_inheritance_mode == "replace"

    def test_inheritance_replace_mode(self):
        """Test that replace mode replaces agent filters with team filters."""
        mock_kb = self._create_mock_knowledge()

        agent = Agent(
            name="Test Agent",
            role="Assistant",
            knowledge=mock_kb,
            knowledge_filters={"type": "api"},  # Agent has its own filters
        )

        team = Team(
            name="Test Team",
            model=OpenAIChat(id="gpt-4o-mini"),
            members=[agent],
            knowledge=mock_kb,
            knowledge_filters={"department": "research"},
            inherit_knowledge_filters_to_agents=True,
            knowledge_filters_inheritance_mode="replace",
        )

        team.initialize_team()

        # Agent filters should be replaced with team filters
        assert agent.knowledge_filters == {"department": "research"}

    def test_inheritance_replace_mode_agent_no_filters(self):
        """Test replace mode when agent has no filters."""
        mock_kb = self._create_mock_knowledge()

        agent = Agent(
            name="Test Agent",
            role="Assistant",
            knowledge=mock_kb,
            # No knowledge_filters set
        )

        team = Team(
            name="Test Team",
            model=OpenAIChat(id="gpt-4o-mini"),
            members=[agent],
            knowledge=mock_kb,
            knowledge_filters={"department": "research"},
            inherit_knowledge_filters_to_agents=True,
            knowledge_filters_inheritance_mode="replace",
        )

        team.initialize_team()

        # Agent should now have team filters
        assert agent.knowledge_filters == {"department": "research"}

    def test_inheritance_merge_team_priority(self):
        """Test merge_team_priority mode - team filters win on conflicts."""
        mock_kb = self._create_mock_knowledge()

        agent = Agent(
            name="Test Agent",
            role="Assistant",
            knowledge=mock_kb,
            knowledge_filters={"type": "api", "version": "v1"},
        )

        team = Team(
            name="Test Team",
            model=OpenAIChat(id="gpt-4o-mini"),
            members=[agent],
            knowledge=mock_kb,
            knowledge_filters={"type": "docs", "department": "research"},  # "type" conflicts
            inherit_knowledge_filters_to_agents=True,
            knowledge_filters_inheritance_mode="merge_team_priority",
        )

        team.initialize_team()

        # Merged: agent's "version" + team's "type" and "department"
        assert agent.knowledge_filters == {
            "type": "docs",  # Team wins on conflict
            "version": "v1",  # Agent's unique key preserved
            "department": "research",  # Team's unique key added
        }

    def test_inheritance_merge_agent_priority(self):
        """Test merge_agent_priority mode - agent filters win on conflicts."""
        mock_kb = self._create_mock_knowledge()

        agent = Agent(
            name="Test Agent",
            role="Assistant",
            knowledge=mock_kb,
            knowledge_filters={"type": "api", "version": "v1"},
        )

        team = Team(
            name="Test Team",
            model=OpenAIChat(id="gpt-4o-mini"),
            members=[agent],
            knowledge=mock_kb,
            knowledge_filters={"type": "docs", "department": "research"},  # "type" conflicts
            inherit_knowledge_filters_to_agents=True,
            knowledge_filters_inheritance_mode="merge_agent_priority",
        )

        team.initialize_team()

        # Merged: team's "department" + agent's "type" and "version"
        assert agent.knowledge_filters == {
            "type": "api",  # Agent wins on conflict
            "version": "v1",  # Agent's unique key preserved
            "department": "research",  # Team's unique key added
        }

    def test_inheritance_merge_agent_priority_no_agent_filters(self):
        """Test merge_agent_priority mode when agent has no filters."""
        mock_kb = self._create_mock_knowledge()

        agent = Agent(
            name="Test Agent",
            role="Assistant",
            knowledge=mock_kb,
            # No knowledge_filters set
        )

        team = Team(
            name="Test Team",
            model=OpenAIChat(id="gpt-4o-mini"),
            members=[agent],
            knowledge=mock_kb,
            knowledge_filters={"department": "research"},
            inherit_knowledge_filters_to_agents=True,
            knowledge_filters_inheritance_mode="merge_agent_priority",
        )

        team.initialize_team()

        # Agent should now have team filters (no agent filters to merge)
        assert agent.knowledge_filters == {"department": "research"}

    def test_no_inheritance_without_team_filters(self):
        """Test that nothing happens if team has no knowledge_filters."""
        mock_kb = self._create_mock_knowledge()

        agent = Agent(
            name="Test Agent",
            role="Assistant",
            knowledge=mock_kb,
            knowledge_filters={"type": "api"},
        )

        team = Team(
            name="Test Team",
            model=OpenAIChat(id="gpt-4o-mini"),
            members=[agent],
            knowledge=mock_kb,
            # No knowledge_filters set
            inherit_knowledge_filters_to_agents=True,
        )

        team.initialize_team()

        # Agent filters should remain unchanged
        assert agent.knowledge_filters == {"type": "api"}

    def test_no_inheritance_without_agent_knowledge(self):
        """Test that inheritance is skipped for agents without knowledge."""
        mock_kb = self._create_mock_knowledge()

        agent = Agent(
            name="Test Agent",
            role="Assistant",
            # No knowledge set
        )

        team = Team(
            name="Test Team",
            model=OpenAIChat(id="gpt-4o-mini"),
            members=[agent],
            knowledge=mock_kb,
            knowledge_filters={"department": "research"},
            inherit_knowledge_filters_to_agents=True,
        )

        team.initialize_team()

        # Agent should not have filters since it has no knowledge
        assert agent.knowledge_filters is None

    def test_inheritance_disabled_preserves_agent_filters(self):
        """Test that when inheritance is disabled, agent filters are preserved."""
        mock_kb = self._create_mock_knowledge()

        agent = Agent(
            name="Test Agent",
            role="Assistant",
            knowledge=mock_kb,
            knowledge_filters={"type": "api"},
        )

        team = Team(
            name="Test Team",
            model=OpenAIChat(id="gpt-4o-mini"),
            members=[agent],
            knowledge=mock_kb,
            knowledge_filters={"department": "research"},
            inherit_knowledge_filters_to_agents=False,  # Explicitly disabled
        )

        team.initialize_team()

        # Agent filters should remain unchanged
        assert agent.knowledge_filters == {"type": "api"}

    def test_multiple_agents_inheritance(self):
        """Test inheritance works correctly with multiple agents."""
        mock_kb = self._create_mock_knowledge()

        agent1 = Agent(
            name="Agent 1",
            role="Researcher",
            knowledge=mock_kb,
            knowledge_filters={"type": "reports"},
        )
        agent2 = Agent(
            name="Agent 2",
            role="Analyst",
            knowledge=mock_kb,
            # No filters
        )
        agent3 = Agent(
            name="Agent 3",
            role="Helper",
            # No knowledge
        )

        team = Team(
            name="Test Team",
            model=OpenAIChat(id="gpt-4o-mini"),
            members=[agent1, agent2, agent3],
            knowledge=mock_kb,
            knowledge_filters={"department": "research"},
            inherit_knowledge_filters_to_agents=True,
            knowledge_filters_inheritance_mode="merge_team_priority",
        )

        team.initialize_team()

        # Agent 1: merged with team priority
        assert agent1.knowledge_filters == {"type": "reports", "department": "research"}

        # Agent 2: gets team filters (had no filters)
        assert agent2.knowledge_filters == {"department": "research"}

        # Agent 3: no change (no knowledge)
        assert agent3.knowledge_filters is None
