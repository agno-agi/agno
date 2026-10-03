"""Missing-db background submits answer 400 on BOTH stream shapes.

The non-stream branch always 400ed; the stream branch entered the detached
streamer, where arun(background=True) raised and the generator converted
it into an SSE error frame under HTTP 200 - the same misconfiguration was
a clean 400 or a 200-then-error depending on stream, and the streaming
client could not distinguish it from a runtime failure.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.os import AgentOS
from agno.team import Team
from agno.workflow import Workflow


@pytest.fixture()
def harness():
    agent = Agent(id="qa-agent", name="QA Agent")
    team = Team(id="qa-team", name="QA Team", members=[agent])
    workflow = Workflow(id="qa-wf", name="QA Workflow", steps=[])
    app = AgentOS(agents=[agent], teams=[team], workflows=[workflow], telemetry=False).get_app()
    return SimpleNamespace(client=TestClient(app, raise_server_exceptions=False))


PATHS = ["/agents/qa-agent/runs", "/teams/qa-team/runs", "/workflows/qa-wf/runs"]


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("stream", ["true", "false"])
def test_background_submit_without_db_is_400_on_both_shapes(harness, path, stream):
    resp = harness.client.post(path, data={"message": "hi", "stream": stream, "background": "true"})
    assert resp.status_code == 400, (
        f"{path} stream={stream}: expected a clean 400, got {resp.status_code} - "
        "a 200-then-SSE-error is indistinguishable from a runtime failure"
    )
    assert "requires a database" in resp.json()["detail"]
