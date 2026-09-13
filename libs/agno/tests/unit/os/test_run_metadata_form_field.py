"""The ``metadata`` run form field is caller input: a bad shape is a 400, never a 500.

``metadata`` is a free-form JSON string, so FastAPI cannot type-check it. The
preview-version stamp merges the route's pinned version into that decoded value,
and an unguarded ``dict(inbound)`` turned every non-object shape a client could
send into an unhandled exception - a 500 from all three run routes.

These tests pin the whole matrix on all three routes (agents, teams, workflows):
a JSON object is accepted and still carries the stamp, every other decodable
shape answers 400, and the two shapes that were already tolerated (undecodable
JSON, an absent field) keep answering 200.
"""

import json
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.schemas.scheduler import COMPONENT_VERSION_METADATA_KEY
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS
from agno.os.utils import stamp_component_version
from agno.registry import Registry
from agno.team.team import Team
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow


class ScriptedModel(Model):
    """A model that answers without a provider call."""

    def __init__(self, model_id: str, reply: str):
        super().__init__(id=model_id, name=model_id, provider="test")
        self._reply = reply

    def _resp(self) -> ModelResponse:
        return ModelResponse(content=self._reply, role="assistant", response_usage=MessageMetrics())

    def invoke(self, *args, **kwargs):
        return self._resp()

    async def ainvoke(self, *args, **kwargs):
        return self._resp()

    def invoke_stream(self, *args, **kwargs):
        yield self._resp()

    async def ainvoke_stream(self, *args, **kwargs):
        yield self._resp()

    def parse_args(self, *args, **kwargs):
        return {}

    def _parse_provider_response(self, response, **kwargs):
        return self._resp()

    def _parse_provider_response_delta(self, response):
        return self._resp()


AGENT_RUNS = "/agents/meta-agent/runs"
TEAM_RUNS = "/teams/meta-team/runs"
WORKFLOW_RUNS = "/workflows/meta-flow/runs"
ALL_RUN_ROUTES = [AGENT_RUNS, TEAM_RUNS, WORKFLOW_RUNS]


@pytest.fixture()
def client(tmp_path) -> TestClient:
    """An AgentOS whose agent, team and workflow are published catalog components."""
    db = SqliteDb(db_file=str(tmp_path / "metadata_form_field.db"))
    model = ScriptedModel("scripted-1", "an answer")
    registry = Registry(name="metadata-registry", dbs=[db], models=[model])
    app = AgentOS(db=db, registry=registry, telemetry=False).get_app()

    agent = Agent(id="meta-agent", name="MetaAgent", model=model)
    agent.save(db=db, stage="published")
    Team(id="meta-team", name="MetaTeam", model=model, members=[agent]).save(db=db, stage="published")
    Workflow(id="meta-flow", name="MetaFlow", steps=[Step(name="s1", agent=agent)]).save(db=db, stage="published")

    return TestClient(app, raise_server_exceptions=False)


def _run(client: TestClient, route: str, *, metadata: Optional[str] = None, version: Optional[int] = None):
    data: Dict[str, str] = {"message": "hi", "stream": "false"}
    if metadata is not None:
        data["metadata"] = metadata
    if version is not None:
        data["version"] = str(version)
    return client.post(route, data=data)


# Shapes a client can put in the field, and the status each must answer with.
REJECTED_SHAPES = [
    ("array", "[1, 2, 3]"),
    ("array_of_pairs", '[["a", 1]]'),
    ("string", '"hello"'),
    ("number", "5"),
    ("bool", "true"),
    ("zero", "0"),
]
ACCEPTED_SHAPES = [
    ("object", '{"a": 1}'),
    ("empty_object", "{}"),
    ("null", "null"),
    ("undecodable", "{bad"),
    ("empty", ""),
]


class TestNonObjectMetadataIsAClientError:
    """Every decodable non-object shape answers 400 on every run route."""

    @pytest.mark.parametrize("route", ALL_RUN_ROUTES)
    @pytest.mark.parametrize("label,raw", REJECTED_SHAPES, ids=[label for label, _ in REJECTED_SHAPES])
    def test_shape_is_rejected(self, client, route, label, raw):
        response = _run(client, route, metadata=raw)
        assert response.status_code == 400, f"{route} {label}: {response.status_code} {response.text[:200]}"
        assert "metadata" in response.json()["detail"].lower()

    @pytest.mark.parametrize("route", ALL_RUN_ROUTES)
    @pytest.mark.parametrize("label,raw", REJECTED_SHAPES, ids=[label for label, _ in REJECTED_SHAPES])
    def test_shape_is_rejected_with_a_pinned_version(self, client, route, label, raw):
        """The stamp is written on the pinned path, so pin the pinned path too."""
        response = _run(client, route, metadata=raw, version=1)
        assert response.status_code == 400, f"{route} {label}: {response.status_code} {response.text[:200]}"


class TestTolerantShapesStillRun:
    """A JSON object, a null, an undecodable value and an absent field all run."""

    @pytest.mark.parametrize("route", ALL_RUN_ROUTES)
    @pytest.mark.parametrize("label,raw", ACCEPTED_SHAPES, ids=[label for label, _ in ACCEPTED_SHAPES])
    def test_shape_is_accepted(self, client, route, label, raw):
        response = _run(client, route, metadata=raw)
        assert response.status_code == 200, f"{route} {label}: {response.status_code} {response.text[:200]}"

    @pytest.mark.parametrize("route", ALL_RUN_ROUTES)
    def test_absent_metadata_runs(self, client, route):
        assert _run(client, route).status_code == 200


class TestObjectMetadataKeepsItsBehaviour:
    """The accepted path is unchanged: caller keys survive and the stamp lands."""

    def test_caller_keys_survive_on_the_run(self, client):
        response = _run(client, AGENT_RUNS, metadata='{"ticket": "T-1"}')
        assert response.status_code == 200
        assert response.json()["metadata"]["ticket"] == "T-1"

    def test_pinned_version_is_stamped_alongside_caller_keys(self, client):
        response = _run(client, AGENT_RUNS, metadata='{"ticket": "T-1"}', version=1)
        assert response.status_code == 200
        metadata = response.json()["metadata"]
        assert metadata["ticket"] == "T-1"
        assert metadata[COMPONENT_VERSION_METADATA_KEY] == 1

    def test_pinned_version_is_stamped_without_caller_metadata(self, client):
        response = _run(client, AGENT_RUNS, version=1)
        assert response.status_code == 200
        assert response.json()["metadata"][COMPONENT_VERSION_METADATA_KEY] == 1

    def test_forged_stamp_is_stripped_on_an_unpinned_run(self, client):
        forged = json.dumps({COMPONENT_VERSION_METADATA_KEY: 99, "ticket": "T-1"})
        response = _run(client, AGENT_RUNS, metadata=forged)
        assert response.status_code == 200
        metadata = response.json()["metadata"]
        assert COMPONENT_VERSION_METADATA_KEY not in metadata
        assert metadata["ticket"] == "T-1"


class TestStampHelperToleratesNonDictMetadata:
    """The helper is also called by non-HTTP callers that build kwargs themselves,
    so it must answer for a non-dict value instead of raising out of the route."""

    @pytest.mark.parametrize("value", [[1, 2, 3], "hello", 5, True, ""])
    def test_unpinned_run_leaves_the_value_alone(self, value: Any):
        kwargs: Dict[str, Any] = {"metadata": value}
        stamp_component_version(kwargs, None)
        assert kwargs["metadata"] == value

    @pytest.mark.parametrize("value", [[1, 2, 3], "hello", 5, True, ""])
    def test_pinned_run_still_records_the_version(self, value: Any):
        kwargs: Dict[str, Any] = {"metadata": value}
        stamp_component_version(kwargs, 3)
        assert kwargs["metadata"] == {COMPONENT_VERSION_METADATA_KEY: 3}

    def test_dict_metadata_is_copied_not_mutated(self):
        original: Dict[str, Any] = {"ticket": "T-1"}
        kwargs: Dict[str, Any] = {"metadata": original}
        stamp_component_version(kwargs, 2)
        assert original == {"ticket": "T-1"}
        assert kwargs["metadata"] == {"ticket": "T-1", COMPONENT_VERSION_METADATA_KEY: 2}

    def test_absent_metadata_stays_absent_when_unpinned(self):
        kwargs: Dict[str, Any] = {}
        stamp_component_version(kwargs, None)
        assert "metadata" not in kwargs


class TestOtherFormFieldsAreUnchanged:
    """The guard is metadata-only: the sibling JSON form fields decoded by the
    same helper keep the shapes they already accepted, which base-branch clients
    rely on. (``dependencies`` answers 500 for a scalar on the base branch too -
    a separate, pre-existing gap that this guard deliberately does not touch.)"""

    @pytest.mark.parametrize("field", ["session_state", "dependencies", "knowledge_filters"])
    @pytest.mark.parametrize("raw", ['{"a": 1}', "[1, 2, 3]", "null", "{bad"])
    def test_sibling_fields_still_run(self, client, field: str, raw: str):
        data: Dict[str, str] = {"message": "hi", "stream": "false", field: raw}
        response = client.post(AGENT_RUNS, data=data)
        assert response.status_code == 200, f"{field}={raw}: {response.status_code} {response.text[:200]}"

    @pytest.mark.parametrize("field", ["session_state", "knowledge_filters"])
    @pytest.mark.parametrize("raw", ['"hello"', "5", "true", ""])
    def test_sibling_scalars_are_not_swept_up(self, client, field: str, raw: str):
        data: Dict[str, str] = {"message": "hi", "stream": "false", field: raw}
        response = client.post(AGENT_RUNS, data=data)
        assert response.status_code == 200, f"{field}={raw}: {response.status_code} {response.text[:200]}"


class TestContinueRouteSharesTheSeam:
    """The continue routes decode the same field through the same helper, so a
    bad shape there is a client error too - never an unhandled exception."""

    @pytest.mark.parametrize(
        "route",
        ["/agents/meta-agent/runs/does-not-exist/continue", "/teams/meta-team/runs/does-not-exist/continue"],
    )
    def test_bad_shape_is_not_a_server_error(self, client, route):
        tools: List[Dict[str, Any]] = []
        response = client.post(route, data={"tools": json.dumps(tools), "stream": "false", "metadata": "[1, 2]"})
        assert response.status_code == 400, f"{route}: {response.status_code} {response.text[:200]}"
