"""Draft catalog reads stay visible without becoming runtime-dispatchable."""

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.os.utils import get_agent_by_id, get_team_by_id, get_workflow_by_id
from agno.team import Team
from agno.workflow import Workflow


@pytest.fixture
def draft_component_client(tmp_path) -> TestClient:
    db = SqliteDb(db_file=str(tmp_path / "draft-component-routes.db"))
    assert Agent(id="draft-agent", name="Draft Agent", db=db).save(stage="draft") == 1
    assert Team(id="draft-team", name="Draft Team", members=[], db=db).save(stage="draft") == 1
    assert Workflow(id="draft-workflow", name="Draft Workflow", db=db).save(stage="draft") == 1

    return TestClient(AgentOS(id="draft-component-os", db=db, telemetry=False).get_app())


@pytest.mark.parametrize(
    ("detail_path", "run_path"),
    [
        ("/agents/draft-agent", "/agents/draft-agent/runs"),
        ("/teams/draft-team", "/teams/draft-team/runs"),
        ("/workflows/draft-workflow", "/workflows/draft-workflow/runs"),
    ],
)
def test_draft_details_are_readable_but_run_dispatch_is_published_only(
    draft_component_client: TestClient,
    detail_path: str,
    run_path: str,
) -> None:
    detail = draft_component_client.get(detail_path)
    dispatched = draft_component_client.post(run_path, data={"message": "must not run", "stream": "false"})

    assert detail.status_code == 200
    assert dispatched.status_code == 404
    assert dispatched.json()["detail"] in {"Agent not found", "Team not found", "Workflow not found"}


def test_exact_version_explicitly_previews_draft_components(tmp_path) -> None:
    db = SqliteDb(db_file=str(tmp_path / "draft-component-preview.db"))
    assert Agent(id="draft-agent", name="Draft Agent", db=db).save(stage="draft") == 1
    assert Team(id="draft-team", name="Draft Team", members=[], db=db).save(stage="draft") == 1
    assert Workflow(id="draft-workflow", name="Draft Workflow", db=db).save(stage="draft") == 1

    assert get_agent_by_id("draft-agent", db=db, version=1) is not None
    assert get_team_by_id("draft-team", db=db, version=1) is not None
    assert get_workflow_by_id("draft-workflow", db=db, version=1) is not None
