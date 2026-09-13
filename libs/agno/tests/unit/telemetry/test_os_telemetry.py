import sys
from contextlib import asynccontextmanager
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.os import AgentOS


def test_os_telemetry_runs_once_in_generated_app_lifespan():
    with patch("agno.api.os.log_os_telemetry") as mock_log:
        agent_os = AgentOS(id="test", agents=[Agent(telemetry=False)])

        assert agent_os.telemetry
        mock_log.assert_not_called()

        app = agent_os.get_app()
        mock_log.assert_not_called()

        with TestClient(app):
            mock_log.assert_called_once()

        mock_log.assert_called_once()
        launch = mock_log.call_args.kwargs["launch"]
        assert launch.os_id == "test"


def test_os_telemetry_preserves_base_app_lifespan_and_runs_once():
    lifespan_events = []

    @asynccontextmanager
    async def base_app_lifespan(_):
        lifespan_events.append("startup")
        yield
        lifespan_events.append("shutdown")

    base_app = FastAPI(lifespan=base_app_lifespan)

    with patch("agno.api.os.log_os_telemetry") as mock_log:
        agent_os = AgentOS(id="test", agents=[Agent(telemetry=False)], base_app=base_app)
        mock_log.assert_not_called()

        app = agent_os.get_app()
        assert app is base_app
        mock_log.assert_not_called()

        with TestClient(app):
            assert lifespan_events == ["startup"]
            mock_log.assert_called_once()

        assert lifespan_events == ["startup", "shutdown"]
        mock_log.assert_called_once()


def test_disabled_os_telemetry_stays_silent_during_app_lifespan():
    with patch("agno.api.os.log_os_telemetry") as mock_log:
        app = AgentOS(id="test", agents=[Agent(telemetry=False)], telemetry=False).get_app()

        with TestClient(app):
            pass

        mock_log.assert_not_called()


def test_os_telemetry_failure_does_not_stop_the_app_from_starting():
    # The launch event is best-effort: a failing telemetry client (including a
    # failed import of it) must not abort the ASGI lifespan.
    with patch("agno.api.os.log_os_telemetry", side_effect=RuntimeError("telemetry down")) as mock_log:
        app = AgentOS(id="test", agents=[Agent(telemetry=False)]).get_app()

        with TestClient(app) as client:
            assert client.get("/health").status_code == 200

        mock_log.assert_called_once()


def test_os_telemetry_import_failure_does_not_stop_the_app_from_starting(monkeypatch):
    # The lifespan imports the telemetry client lazily; an unimportable module
    # (what a broken settings import looks like) must not abort startup.
    monkeypatch.setitem(sys.modules, "agno.api.os", None)
    app = AgentOS(id="test", agents=[Agent(telemetry=False)]).get_app()

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
