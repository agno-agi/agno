from agno.agent import _init, _response, _run, _storage, _tools
from agno.agent.agent import Agent
from agno.run.agent import RunOutput
from agno.run.base import RunStatus


def _patch_sync_dispatch_dependencies(agent, monkeypatch, runs=None):
    monkeypatch.setattr(_init, "has_async_db", lambda agent: False)
    monkeypatch.setattr(_storage, "update_metadata", lambda agent, session=None: None)
    monkeypatch.setattr(_storage, "load_session_state", lambda agent, session=None, session_state=None: session_state)
    monkeypatch.setattr(_run, "resolve_run_dependencies", lambda agent, run_context: None)
    monkeypatch.setattr(_response, "get_response_format", lambda agent, run_context=None: None)
    monkeypatch.setattr(_tools, "determine_tools_for_model", lambda *a, **kw: [])

    # Needs a mock session
    class MockSession:
        def __init__(self, session_id, user_id, runs):
            self.session_id = session_id
            self.user_id = user_id
            self.runs = runs

    monkeypatch.setattr(
        _storage,
        "read_or_create_session",
        lambda agent, session_id=None, user_id=None: MockSession(session_id=session_id, user_id=user_id, runs=runs),
    )


def _make_agent(monkeypatch, runs=None):
    agent = Agent(name="test-agent")
    _patch_sync_dispatch_dependencies(agent, monkeypatch, runs=runs)
    monkeypatch.setattr(agent, "initialize_agent", lambda debug_mode=None: None)
    return agent


def test_continue_run_rebinds_run_context_run_id(monkeypatch):
    """
    Test that when a run is forked, the run_context injected into
    _continue_run has the newly generated run_id, not the parent's run_id.
    """
    original = RunOutput(run_id="parent-run", session_id="session-1", status=RunStatus.completed)
    agent = _make_agent(monkeypatch, runs=[original])

    captured = {}

    def fake_continue_run(agent, run_response, run_messages, run_context, session, tools, **kw):
        captured["run_context_run_id"] = run_context.run_id
        captured["run_response_run_id"] = run_response.run_id
        return run_response

    monkeypatch.setattr(_run, "_continue_run", fake_continue_run)

    _run.continue_run_dispatch(
        agent=agent, run_id="parent-run", session_id="session-1", fork=True, continue_from=1, stream=False
    )

    assert captured["run_response_run_id"] != "parent-run", "Fork should generate a new run_id"
    assert captured["run_context_run_id"] == captured["run_response_run_id"], (
        "run_context.run_id should match the new forked run_id"
    )
