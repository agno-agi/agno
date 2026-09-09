"""Unit tests for cumulative session-level token usage metrics."""

from agno.metrics import ModelMetrics, RunMetrics, SessionMetrics
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.session.agent import AgentSession
from agno.session.team import TeamSession

# ---------------------------------------------------------------------------
# AgentSession.session_metrics property
# ---------------------------------------------------------------------------


class TestAgentSessionMetricsProperty:
    def test_returns_none_when_session_data_is_none(self):
        session = AgentSession(session_id="s1", session_data=None)
        assert session.session_metrics is None

    def test_returns_none_when_no_metrics_key(self):
        session = AgentSession(session_id="s1", session_data={})
        assert session.session_metrics is None

    def test_reads_from_dict(self):
        session = AgentSession(
            session_id="s1",
            session_data={
                "session_metrics": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "total_tokens": 150,
                }
            },
        )
        metrics = session.session_metrics
        assert metrics is not None
        assert metrics.input_tokens == 100
        assert metrics.output_tokens == 50
        assert metrics.total_tokens == 150

    def test_reads_session_metrics_object(self):
        sm = SessionMetrics(input_tokens=10, output_tokens=5, total_tokens=15)
        session = AgentSession(session_id="s1", session_data={"session_metrics": sm})
        metrics = session.session_metrics
        assert metrics is not None
        assert metrics.input_tokens == 10

    def test_reads_legacy_run_metrics(self):
        rm = RunMetrics(input_tokens=20, output_tokens=10, total_tokens=30)
        session = AgentSession(session_id="s1", session_data={"session_metrics": rm})
        metrics = session.session_metrics
        assert isinstance(metrics, SessionMetrics)
        assert metrics.input_tokens == 20
        assert metrics.total_tokens == 30

    def test_setter_creates_session_data(self):
        session = AgentSession(session_id="s1", session_data=None)
        sm = SessionMetrics(input_tokens=5, output_tokens=3, total_tokens=8)
        session.session_metrics = sm
        assert session.session_data is not None
        assert "session_metrics" in session.session_data

    def test_setter_writes_dict(self):
        session = AgentSession(session_id="s1", session_data={})
        sm = SessionMetrics(input_tokens=5, output_tokens=3, total_tokens=8)
        session.session_metrics = sm
        raw = session.session_data["session_metrics"]
        assert isinstance(raw, dict)
        assert raw["input_tokens"] == 5

    def test_setter_none_removes_key(self):
        session = AgentSession(
            session_id="s1",
            session_data={"session_metrics": {"input_tokens": 1}},
        )
        session.session_metrics = None
        assert "session_metrics" not in session.session_data

    def test_roundtrip_via_property(self):
        session = AgentSession(session_id="s1", session_data={})
        sm = SessionMetrics(
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            cost=0.01,
        )
        session.session_metrics = sm
        result = session.session_metrics
        assert result is not None
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert result.total_tokens == 150
        assert result.cost == 0.01


# ---------------------------------------------------------------------------
# TeamSession.session_metrics property
# ---------------------------------------------------------------------------


class TestTeamSessionMetricsProperty:
    def test_returns_none_when_session_data_is_none(self):
        session = TeamSession(session_id="s1", session_data=None)
        assert session.session_metrics is None

    def test_returns_none_when_no_metrics_key(self):
        session = TeamSession(session_id="s1", session_data={})
        assert session.session_metrics is None

    def test_reads_from_dict(self):
        session = TeamSession(
            session_id="s1",
            session_data={
                "session_metrics": {
                    "input_tokens": 200,
                    "output_tokens": 100,
                    "total_tokens": 300,
                }
            },
        )
        metrics = session.session_metrics
        assert metrics is not None
        assert metrics.input_tokens == 200
        assert metrics.output_tokens == 100
        assert metrics.total_tokens == 300

    def test_setter_roundtrip(self):
        session = TeamSession(session_id="s1", session_data={})
        sm = SessionMetrics(
            input_tokens=50,
            output_tokens=25,
            total_tokens=75,
            cost=0.005,
        )
        session.session_metrics = sm
        result = session.session_metrics
        assert result is not None
        assert result.input_tokens == 50
        assert result.cost == 0.005


# ---------------------------------------------------------------------------
# Metrics accumulation across runs
# ---------------------------------------------------------------------------


class TestMetricsAccumulationAgent:
    def _make_run(self, run_id: str, input_tokens: int, output_tokens: int) -> RunOutput:
        return RunOutput(
            run_id=run_id,
            agent_id="agent-1",
            metrics=RunMetrics(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            ),
        )

    def test_accumulate_single_run(self):
        session = AgentSession(session_id="s1", session_data={})
        run = self._make_run("r1", 100, 50)
        sm = SessionMetrics()
        sm.accumulate_from_run(run.metrics)
        session.session_metrics = sm
        result = session.session_metrics
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert result.total_tokens == 150

    def test_accumulate_multiple_runs(self):
        session = AgentSession(session_id="s1", session_data={})
        sm = SessionMetrics()
        for i, (inp, out) in enumerate([(100, 50), (200, 80), (50, 20)]):
            run = self._make_run(f"r{i}", inp, out)
            sm.accumulate_from_run(run.metrics)
        session.session_metrics = sm
        result = session.session_metrics
        assert result.input_tokens == 350
        assert result.output_tokens == 150
        assert result.total_tokens == 500

    def test_accumulate_preserves_model_details(self):
        run = RunOutput(
            run_id="r1",
            agent_id="agent-1",
            metrics=RunMetrics(
                input_tokens=100,
                output_tokens=50,
                total_tokens=150,
                details={
                    "model": [
                        ModelMetrics(
                            id="gpt-4o",
                            provider="openai",
                            input_tokens=100,
                            output_tokens=50,
                            total_tokens=150,
                        )
                    ]
                },
            ),
        )
        sm = SessionMetrics()
        sm.accumulate_from_run(run.metrics)
        assert sm.details is not None
        assert "model" in sm.details
        assert sm.details["model"][0].id == "gpt-4o"
        assert sm.details["model"][0].input_tokens == 100

    def test_accumulate_with_cost(self):
        session = AgentSession(session_id="s1", session_data={})
        sm = SessionMetrics()
        run1 = RunOutput(
            run_id="r1",
            agent_id="a",
            metrics=RunMetrics(input_tokens=10, output_tokens=5, total_tokens=15, cost=0.01),
        )
        run2 = RunOutput(
            run_id="r2",
            agent_id="a",
            metrics=RunMetrics(input_tokens=20, output_tokens=10, total_tokens=30, cost=0.02),
        )
        sm.accumulate_from_run(run1.metrics)
        sm.accumulate_from_run(run2.metrics)
        session.session_metrics = sm
        result = session.session_metrics
        assert result.cost == 0.03
        assert result.input_tokens == 30


class TestMetricsAccumulationTeam:
    def test_accumulate_team_with_members(self):
        """Metrics from team leader + member runs should accumulate."""
        member_run = RunOutput(
            run_id="mr1",
            agent_id="member-1",
            parent_run_id="tr1",
            metrics=RunMetrics(input_tokens=50, output_tokens=25, total_tokens=75),
        )
        team_run = TeamRunOutput(
            run_id="tr1",
            team_id="team-1",
            metrics=RunMetrics(input_tokens=100, output_tokens=50, total_tokens=150),
            member_responses=[member_run],
        )
        sm = SessionMetrics()
        # Accumulate leader metrics
        sm.accumulate_from_run(team_run.metrics)
        # Accumulate member metrics
        for member in team_run.member_responses:
            if member.metrics is not None:
                sm.accumulate_from_run(member.metrics)

        session = TeamSession(session_id="s1", session_data={})
        session.session_metrics = sm
        result = session.session_metrics
        assert result.input_tokens == 150
        assert result.output_tokens == 75
        assert result.total_tokens == 225


# ---------------------------------------------------------------------------
# Serialization roundtrip with metrics
# ---------------------------------------------------------------------------


class TestSerializationWithMetrics:
    def test_agent_session_to_dict_includes_metrics_in_session_data(self):
        session = AgentSession(session_id="s1", session_data={})
        session.session_metrics = SessionMetrics(input_tokens=10, output_tokens=5, total_tokens=15)
        d = session.to_dict()
        assert d["session_data"]["session_metrics"]["input_tokens"] == 10

    def test_agent_session_roundtrip(self):
        session = AgentSession(session_id="s1", session_data={})
        session.session_metrics = SessionMetrics(input_tokens=10, output_tokens=5, total_tokens=15)
        d = session.to_dict()
        restored = AgentSession.from_dict(d)
        assert restored.session_metrics is not None
        assert restored.session_metrics.input_tokens == 10
        assert restored.session_metrics.total_tokens == 15

    def test_team_session_to_dict_includes_metrics_in_session_data(self):
        session = TeamSession(session_id="s1", session_data={})
        session.session_metrics = SessionMetrics(input_tokens=20, output_tokens=10, total_tokens=30)
        d = session.to_dict()
        assert d["session_data"]["session_metrics"]["input_tokens"] == 20

    def test_team_session_roundtrip(self):
        session = TeamSession(session_id="s1", session_data={})
        session.session_metrics = SessionMetrics(input_tokens=20, output_tokens=10, total_tokens=30, cost=0.05)
        d = session.to_dict()
        restored = TeamSession.from_dict(d)
        assert restored.session_metrics is not None
        assert restored.session_metrics.input_tokens == 20
        assert restored.session_metrics.cost == 0.05
