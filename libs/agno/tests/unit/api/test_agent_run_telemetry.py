from unittest.mock import patch

from agno.api.agent import create_agent_run
from agno.api.schemas.agent import AgentRunCreate


def test_create_agent_run_uses_background_thread():
    run = AgentRunCreate(session_id="session", run_id="run", data={"model": "local"})

    with patch("agno.api.agent.Thread") as thread_cls:
        thread = thread_cls.return_value

        create_agent_run(run)

    thread_cls.assert_called_once()
    assert thread_cls.call_args.kwargs["target"].__name__ == "_send_agent_run"
    assert thread_cls.call_args.kwargs["args"] == (run,)
    assert thread_cls.call_args.kwargs["daemon"] is True
    thread.start.assert_called_once_with()
