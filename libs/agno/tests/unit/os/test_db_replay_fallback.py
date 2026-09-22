"""The DB replay fallback (PATH-3) must honor the client's
last_event_index using the events' REAL stream indices.

Substrate: the event stream stamps event_index onto the event OBJECT at
publish, and the component's session save persists it - stream indices are
NOT gapless (retries and continuation legs leave real gaps), so the old
positional renumbering both duplicated already-consumed events and destroyed
index continuity. The worker-path test is the tripwire for the
shared-reference assumption: if the worker's published events ever stop
being the objects the component accumulates, indices silently stop reaching
storage and the fallback quietly regresses.
"""

import json
from types import SimpleNamespace

import pytest

from agno.run.agent import RunContentEvent
from agno.run.base import RunStatus


def make_events(indices):
    events = []
    for i in indices:
        e = RunContentEvent(content=f"c{i}", run_id="r1")
        if i is not None:
            e.event_index = i
        events.append(e)
    return events


def frame_indices(frames):
    out = []
    for f in frames[1:]:  # frames[0] is the replay meta
        payload = json.loads(f.split("data: ", 1)[1])
        out.append(payload["event_index"])
    return out


class TestStoredEventReplayFrames:
    # Helper imported per-test (not module-level) so the ROUTER-level tests
    # below still collect on unfixed source and fail behaviorally there
    def test_gapped_indices_filtered_by_floor_and_preserved(self):
        """Retry/continuation gaps are real: [0, 1, 5, 6] with floor=1 must
        replay exactly 5 and 6 under their stored indices - never compacted."""
        from agno.os.utils import stored_event_replay_frames

        run = SimpleNamespace(events=make_events([0, 1, 5, 6]), status=RunStatus.completed)
        frames = stored_event_replay_frames(run, "r1", last_event_index=1)
        assert frame_indices(frames) == [5, 6]
        meta = json.loads(frames[0].split("data: ", 1)[1])
        assert meta["total_events"] == 2

    def test_no_floor_replays_all_with_stored_indices(self):
        from agno.os.utils import stored_event_replay_frames

        run = SimpleNamespace(events=make_events([0, 3, 7]), status=RunStatus.completed)
        frames = stored_event_replay_frames(run, "r1", last_event_index=None)
        assert frame_indices(frames) == [0, 3, 7]

    def test_legacy_unstamped_events_keep_positional_numbering_unfiltered(self):
        """Pre-stamp rows: a floor from live-stream indices does not speak
        their numbering - never filter them, keep the positional fallback."""
        from agno.os.utils import stored_event_replay_frames

        run = SimpleNamespace(events=make_events([None, None, None]), status=RunStatus.completed)
        frames = stored_event_replay_frames(run, "r1", last_event_index=1)
        assert frame_indices(frames) == [0, 1, 2]

    def test_mixed_row_filters_only_stamped_events(self):
        from agno.os.utils import stored_event_replay_frames

        run = SimpleNamespace(events=make_events([None, 4, 9]), status=RunStatus.completed)
        frames = stored_event_replay_frames(run, "r1", last_event_index=4)
        assert frame_indices(frames) == [0, 9]


class TestResumeEndpointHonorsFloor:
    """Router-level: the real resume endpoint, PATH-3 (event stream knows
    nothing about the run), stored events with a continuation-leg gap."""

    @pytest.fixture()
    def harness(self, tmp_path):
        from fastapi.testclient import TestClient

        from agno.agent import Agent
        from agno.db.sqlite import SqliteDb
        from agno.os import AgentOS
        from agno.run.agent import RunOutput
        from agno.session import AgentSession

        db = SqliteDb(db_file=str(tmp_path / "t.db"))
        agent = Agent(id="qa-agent", name="QA Agent", db=db)
        app = AgentOS(agents=[agent], telemetry=False).get_app()
        events = make_events([0, 1, 5, 6])
        run = RunOutput(
            run_id="r-replay",
            session_id="s-replay",
            agent_id="qa-agent",
            status=RunStatus.completed,
            content="done",
            events=events,
        )
        import time

        session = AgentSession(session_id="s-replay", agent_id="qa-agent", created_at=int(time.time()))
        db.upsert_session(session)
        # v3 substrate: runs persist via the per-run save, not the session row
        db.upsert_run(run=run, session_id="s-replay")
        return TestClient(app, raise_server_exceptions=False)

    def test_resume_with_floor_replays_only_missed_events_with_real_indices(self, harness):
        resp = harness.post(
            "/agents/qa-agent/runs/r-replay/resume",
            data={"last_event_index": "1", "session_id": "s-replay"},
        )
        assert resp.status_code == 200
        indices = [
            json.loads(line.split("data: ", 1)[1])["event_index"]
            for line in resp.text.split("\n")
            if line.startswith("data: ") and '"event": "replay"' not in line
        ]
        assert indices == [5, 6], (
            f"expected only the missed events under their REAL indices, got {indices} - "
            "positional renumbering duplicates consumed events and breaks continuity"
        )

    def test_resume_without_floor_replays_all_preserving_gaps(self, harness):
        resp = harness.post(
            "/agents/qa-agent/runs/r-replay/resume",
            data={"session_id": "s-replay"},
        )
        assert resp.status_code == 200
        indices = [
            json.loads(line.split("data: ", 1)[1])["event_index"]
            for line in resp.text.split("\n")
            if line.startswith("data: ") and '"event": "replay"' not in line
        ]
        assert indices == [0, 1, 5, 6], f"gaps must survive the DB round-trip, got {indices}"
