"""Round 9 bug reproduction tests.

Tests verify bugs found during the R9 audit of unaudited modules and high-churn areas:
- AgentOS (os/), agent/_run.py, team/_run.py
- approval/, eval/, tracing/
"""

import inspect
import re

import pytest


class TestBUG026HookNormalizationStateLeak:
    """BUG-026: Hook normalization flag shared between sync and async run modes.

    The _hooks_normalised flag is a single boolean. Whichever run mode (sync or async)
    is called first normalizes the hooks for that mode and sets the flag. The second
    mode skips normalization and uses hooks prepared for the wrong mode.
    """

    def test_agent_single_shared_flag(self):
        """Verify that agent uses a single _hooks_normalised flag for both modes."""
        from agno.agent.agent import Agent

        agent = Agent.__new__(Agent)
        agent._hooks_normalised = False

        assert hasattr(agent, "_hooks_normalised")
        assert not hasattr(agent, "_hooks_normalised_sync")
        assert not hasattr(agent, "_hooks_normalised_async")

    def test_team_single_shared_flag(self):
        """Verify that team uses a single _hooks_normalised flag for both modes."""
        from agno.team.team import Team

        team = Team.__new__(Team)
        team._hooks_normalised = False

        assert hasattr(team, "_hooks_normalised")
        assert not hasattr(team, "_hooks_normalised_sync")
        assert not hasattr(team, "_hooks_normalised_async")

    def test_normalize_pre_hooks_produces_different_callables_per_mode(self):
        """Verify that normalize_pre_hooks with async_mode=True vs False produces different callables."""
        from agno.guardrails.base import BaseGuardrail
        from agno.utils.hooks import normalize_pre_hooks

        class DummyGuardrail(BaseGuardrail):
            def check(self, **kwargs):
                pass

            async def async_check(self, **kwargs):
                pass

        guardrail = DummyGuardrail()
        hooks = [guardrail]

        sync_normalized = normalize_pre_hooks(list(hooks))
        async_normalized = normalize_pre_hooks(list(hooks), async_mode=True)

        assert sync_normalized is not None
        assert async_normalized is not None
        assert len(sync_normalized) == 1
        assert len(async_normalized) == 1
        # The key issue: sync gets .check, async gets .async_check
        # If we normalize once and reuse, the wrong callable is used
        assert sync_normalized[0] != async_normalized[0]

    def test_sync_run_dispatch_sets_flag_without_mode(self):
        """Verify sync run_dispatch normalizes without async_mode and sets shared flag."""
        source = inspect.getsource(__import__("agno.agent._run", fromlist=["_run"]))

        # Find the sync normalization block
        sync_pattern = re.search(
            r"if not agent\._hooks_normalised:.*?agent\._hooks_normalised = True",
            source,
            re.DOTALL,
        )
        assert sync_pattern is not None
        block = sync_pattern.group()

        # Verify sync uses normalize_pre_hooks without async_mode=True
        assert (
            "normalize_pre_hooks(agent.pre_hooks)" in block
            or "normalize_pre_hooks(agent.pre_hooks, async_mode=False)" in block
            or (
                "normalize_pre_hooks(agent.pre_hooks)" in block
                and "async_mode=True" not in block.split("normalize_pre_hooks(agent.pre_hooks)")[0]
            )
        )

    def test_async_run_dispatch_sets_same_flag(self):
        """Verify async run_dispatch sets the SAME _hooks_normalised flag."""
        source = inspect.getsource(__import__("agno.agent._run", fromlist=["_run"]))

        # Count how many times _hooks_normalised is set to True
        set_count = len(re.findall(r"agent\._hooks_normalised\s*=\s*True", source))
        # Should be 2 (sync and async), both setting the SAME flag
        assert set_count == 2, f"Expected 2 flag sets, found {set_count}"

        # Verify both sync and async normalize hooks into the same agent.pre_hooks
        normalize_calls = re.findall(r"agent\.pre_hooks\s*=\s*normalize_pre_hooks\(.*?\)", source, re.DOTALL)
        assert len(normalize_calls) >= 2, "Expected at least 2 normalize_pre_hooks calls"


class TestBUG029AccuracyResultUninitializedFields:
    """BUG-029: AccuracyResult dataclass fields uninitialized when results list is empty.

    Fields like avg_score, mean_score, etc. are declared with field(init=False) but
    only set inside compute_stats() when results is non-empty. Empty results
    leaves them unset, causing AttributeError on access.
    """

    def test_empty_results_raises_attribute_error(self):
        """Verify that AccuracyResult with empty results has unset stat fields."""
        from agno.eval.accuracy import AccuracyResult

        result = AccuracyResult(results=[])

        with pytest.raises(AttributeError):
            _ = result.avg_score

    def test_empty_results_print_summary_crashes(self):
        """Verify that print_summary on empty results would crash."""
        from agno.eval.accuracy import AccuracyResult

        result = AccuracyResult(results=[])

        # print_summary checks "if self.avg_score is not None" which raises AttributeError
        with pytest.raises(AttributeError):
            result.print_summary()

    def test_non_empty_results_works(self):
        """Control: non-empty results correctly initializes stats."""
        from agno.eval.accuracy import AccuracyEvaluation, AccuracyResult

        eval1 = AccuracyEvaluation(input="test", output="out", expected_output="exp", score=8, reason="good")
        result = AccuracyResult(results=[eval1])
        assert result.avg_score == 8.0


class TestBUG031ReloadIncludesOverwrite:
    """BUG-031: AgentOS.serve() overwrites user-provided reload_includes.

    Line 1343: `if reload and reload_includes is not None:` should be
    `if reload and reload_includes is None:` — the condition is inverted.
    """

    def test_reload_includes_overwrite_condition(self):
        """Verify the condition overwrites when user provides includes (is not None)."""
        source = inspect.getsource(__import__("agno.os.app", fromlist=["app"]).AgentOS.serve)

        # The buggy condition: replaces user's includes instead of setting defaults
        assert "reload_includes is not None" in source
        # When this condition is True (user provided includes), it replaces them
        assert 'reload_includes = ["*.yaml", "*.yml"]' in source


class TestBUG032WorkflowSessionNameLost:
    """BUG-032: WorkflowSession.workflow_name lost in DB round-trip.

    WorkflowSession.to_dict() serializes workflow_name but DB adapters
    don't store or restore it.
    """

    def test_workflow_session_has_workflow_name(self):
        """Verify WorkflowSession serializes workflow_name."""
        from agno.session.workflow import WorkflowSession

        session = WorkflowSession(
            session_id="test",
            workflow_id="wf-1",
            workflow_name="My Workflow",
        )
        d = session.to_dict()
        assert "workflow_name" in d
        assert d["workflow_name"] == "My Workflow"

    def test_sqlite_upsert_omits_workflow_name(self):
        """Verify SQLite adapter doesn't store workflow_name."""
        source = inspect.getsource(__import__("agno.db.sqlite.sqlite", fromlist=["sqlite"]).SqliteDb.upsert_session)

        # The workflow branch is the else: block (after AgentSession and TeamSession isinstance checks).
        # It stores workflow_id and workflow_data but NOT workflow_name.
        assert "workflow_id" in source, "upsert_session should reference workflow_id"
        assert "workflow_name" not in source, "Bug already fixed — workflow_name is now stored"


class TestBUG033AgentSessionFieldsLost:
    """BUG-033: AgentSession.team_id and workflow_id lost in DB round-trip.

    AgentSession has team_id and workflow_id fields that are serialized
    by to_dict() but not persisted by DB adapters.
    """

    def test_agent_session_has_team_id_and_workflow_id(self):
        """Verify AgentSession serializes team_id and workflow_id."""
        from agno.session.agent import AgentSession

        session = AgentSession(
            session_id="test",
            agent_id="agent-1",
            team_id="team-1",
            workflow_id="wf-1",
        )
        d = session.to_dict()
        assert "team_id" in d
        assert d["team_id"] == "team-1"
        assert "workflow_id" in d
        assert d["workflow_id"] == "wf-1"

    def test_sqlite_agent_upsert_omits_team_id_and_workflow_id(self):
        """Verify SQLite adapter doesn't store AgentSession.team_id or workflow_id."""
        source = inspect.getsource(__import__("agno.db.sqlite.sqlite", fromlist=["sqlite"]).SqliteDb.upsert_session)

        # Find the AgentSession insert block and check for team_id and workflow_id
        lines = source.split("\n")
        in_agent_block = False
        has_team_id = False
        has_workflow_id = False
        for line in lines:
            if "isinstance(session, AgentSession)" in line:
                in_agent_block = True
            if in_agent_block and "isinstance(session, TeamSession)" in line:
                break
            if in_agent_block and "team_id" in line and "serialized_session" in line:
                has_team_id = True
            if in_agent_block and "workflow_id" in line and "serialized_session" in line:
                has_workflow_id = True

        assert not has_team_id, "Bug already fixed — team_id is now stored in AgentSession"
        assert not has_workflow_id, "Bug already fixed — workflow_id is now stored in AgentSession"
