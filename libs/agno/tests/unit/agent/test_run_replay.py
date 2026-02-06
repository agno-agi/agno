import json
from pathlib import Path

from agno.agent.agent import Agent
from agno.agent.trait.replay import prepare_replay_record
from agno.agent.trait.run_options import ReplayMode, ResolvedRunOptions
from agno.db.base import SessionType
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.message import Message
from agno.run import RunContext, RunStatus
from agno.run.agent import RunInput, RunOutput
from agno.session.agent import AgentSession


def _build_run_output(run_id: str, session_id: str, status: RunStatus, content: str) -> RunOutput:
    return RunOutput(
        run_id=run_id,
        session_id=session_id,
        agent_id="agent-1",
        user_id="user-1",
        input=RunInput(input_content="hello"),
        content=content,
        status=status,
        created_at=3,
        messages=[
            Message(id=f"{run_id}-u", role="user", content="hello", created_at=1),
            Message(id=f"{run_id}-a", role="assistant", content=content, created_at=2),
        ],
    )


def _build_options(
    *,
    replay_mode: ReplayMode,
    replay_max_payload_bytes: int = 262_144,
    replay_max_message_chars: int = 4_000,
) -> ResolvedRunOptions:
    return ResolvedRunOptions(
        stream=False,
        stream_events=False,
        yield_run_output=False,
        add_history_to_context=False,
        add_dependencies_to_context=False,
        add_session_state_to_context=False,
        dependencies=None,
        knowledge_filters=None,
        metadata=None,
        output_schema=None,
        replay_mode=replay_mode,
        replay_sample_rate=1.0,
        replay_max_payload_bytes=replay_max_payload_bytes,
        replay_max_message_chars=replay_max_message_chars,
        replay_compress_payload=False,
    )


def _persist_run(
    tmp_path: Path,
    replay_mode: ReplayMode,
    status: RunStatus,
    content: str,
    run_id: str,
    db_name: str,
):
    db = SqliteDb(db_file=str(tmp_path / f"{db_name}.db"))
    agent = Agent(id="agent-1", db=db)

    session = AgentSession(
        session_id="session-1",
        agent_id="agent-1",
        user_id="user-1",
        session_data={"session_state": {}},
        created_at=1,
    )
    run_context = RunContext(run_id=run_id, session_id="session-1", user_id="user-1", session_state={})
    run_response = _build_run_output(run_id=run_id, session_id="session-1", status=status, content=content)

    agent._set_resolved_run_options(run_id, _build_options(replay_mode=replay_mode))
    agent._create_run_engine(run_id)
    agent._cleanup_and_store(run_response=run_response, session=session, run_context=run_context, user_id="user-1")

    stored_session = db.get_session("session-1", SessionType.AGENT, deserialize=False)
    return db, stored_session


def test_replay_not_written_when_mode_off(tmp_path):
    db, _ = _persist_run(
        tmp_path=tmp_path,
        replay_mode=ReplayMode.OFF,
        status=RunStatus.completed,
        content="ok",
        run_id="run-off",
        db_name="run-off",
    )
    assert db.get_replay("run-off") is None


def test_replay_written_on_error_in_errors_only_mode(tmp_path):
    db, _ = _persist_run(
        tmp_path=tmp_path,
        replay_mode=ReplayMode.ERRORS_ONLY,
        status=RunStatus.error,
        content="boom",
        run_id="run-error",
        db_name="run-error",
    )
    replay = db.get_replay("run-error")
    assert replay is not None
    assert replay["status"] == "error"
    assert replay["mode"] == ReplayMode.ERRORS_ONLY.value


def test_replay_truncation_limits_payload_size():
    run_response = _build_run_output(
        run_id="run-truncate",
        session_id="session-1",
        status=RunStatus.error,
        content="x" * 10_000,
    )
    options = _build_options(
        replay_mode=ReplayMode.FULL,
        replay_max_payload_bytes=512,
        replay_max_message_chars=64,
    )

    replay = prepare_replay_record(run_response=run_response, run_context=None, options=options)

    assert replay is not None
    assert replay["truncated"] is True
    assert replay["payload_bytes"] <= 512
    assert replay["payload"]["truncation"]["truncated"] is True


def test_session_payload_does_not_include_replay_blob(tmp_path):
    db_off, session_off = _persist_run(
        tmp_path=tmp_path,
        replay_mode=ReplayMode.OFF,
        status=RunStatus.completed,
        content="stable-content",
        run_id="run-session",
        db_name="run-session-off",
    )
    db_full, session_full = _persist_run(
        tmp_path=tmp_path,
        replay_mode=ReplayMode.FULL,
        status=RunStatus.completed,
        content="stable-content",
        run_id="run-session",
        db_name="run-session-full",
    )

    assert session_off is not None
    assert session_full is not None
    assert db_off.get_replay("run-session") is None
    assert db_full.get_replay("run-session") is not None

    runs_off = session_off["runs"]
    runs_full = session_full["runs"]
    assert isinstance(runs_off, list)
    assert isinstance(runs_full, list)
    assert "payload" not in runs_full[0]
    assert "payload_encoding" not in runs_full[0]

    assert len(json.dumps(runs_full, sort_keys=True)) == len(json.dumps(runs_off, sort_keys=True))
