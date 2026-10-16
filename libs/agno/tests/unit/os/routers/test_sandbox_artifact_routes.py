"""The generated OpenAPI contract of the sandbox artifact download route.

The sandbox routes are registered on every AgentOS agent router, so an ordinary
agent is enough to read their schema; no sandbox infrastructure is involved.
"""

import pytest

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS

DOWNLOAD = "/agents/{agent_id}/sessions/{session_id}/sandbox/artifact"


@pytest.fixture
def download_responses(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "sandbox_schema.db"))
    agent = Agent(id="plain", name="Plain", db=db)
    app = AgentOS(id="sandbox-schema-os", agents=[agent], db=db, telemetry=False).get_app()
    return app.openapi()["paths"][DOWNLOAD]["get"]["responses"]


def test_artifact_download_declares_binary_content(download_responses):
    content = download_responses["200"]["content"]
    assert content["application/octet-stream"]["schema"] == {"type": "string", "format": "binary"}


def test_artifact_download_does_not_advertise_json(download_responses):
    assert "application/json" not in download_responses["200"]["content"]
