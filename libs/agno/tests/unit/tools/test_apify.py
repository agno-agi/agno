"""Unit tests for ApifyTools class."""

import json
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

pytest.importorskip("apify_client")

from agno.tools.apify import ApifyTools, get_actor_latest_build, response_to_dict  # noqa: E402

ACTOR_ID = "apify/website-content-crawler"
TOOL_NAME = "apify_actor_apify_website-content-crawler"

BUILD_RESPONSE = {
    "data": {
        "actorDefinition": {
            "description": "Crawls websites and extracts text content.",
            "input": {
                "properties": {
                    "startUrls": {"type": "array", "description": "URLs to start crawling from."},
                    "maxCrawlPages": {"type": "integer", "description": "Maximum pages to crawl.", "default": 10},
                },
                "required": ["startUrls"],
            },
        }
    }
}


class ApifyModel(BaseModel):
    """Stand-in for the Pydantic models returned by apify-client 3.x, with the same model config."""

    model_config = ConfigDict(extra="allow", populate_by_name=True, alias_generator=to_camel)


class Actor(ApifyModel):
    id: str
    name: str


class Run(ApifyModel):
    id: str
    default_dataset_id: Optional[str] = None


# apify-client 2.x returns dicts, apify-client 3.x returns Pydantic models
ACTOR_RESPONSES = {
    "dict": {"id": "actor-id", "name": "website-content-crawler"},
    "model": Actor(id="actor-id", name="website-content-crawler"),
}
RUN_RESPONSES = {
    "dict": {"id": "run-id", "defaultDatasetId": "dataset-id"},
    "model": Run(id="run-id", default_dataset_id="dataset-id"),
}


@pytest.fixture(params=["dict", "model"])
def mock_client(request):
    """Create a mock Apify client that returns dicts (2.x) or models (3.x)."""
    client = MagicMock()
    client.actor.return_value.get.return_value = ACTOR_RESPONSES[request.param]
    client.actor.return_value.call.return_value = RUN_RESPONSES[request.param]
    client.run.return_value.dataset.return_value.list_items.return_value.items = [{"text": "Example page"}]
    with patch("agno.tools.apify.create_apify_client", return_value=client):
        yield client


@pytest.fixture
def mock_requests():
    """Mock the request for the Actor's default build."""
    with patch("agno.tools.apify.requests") as mock_requests:
        mock_requests.request.return_value.json.return_value = BUILD_RESPONSE
        yield mock_requests


def test_response_to_dict_returns_dict_unchanged():
    """A dict from apify-client 2.x is returned as is."""
    response = RUN_RESPONSES["dict"]
    assert response_to_dict(response) is response


def test_response_to_dict_dumps_model_with_api_field_names():
    """A model from apify-client 3.x is dumped with the same keys the API and 2.x use."""
    assert response_to_dict(RUN_RESPONSES["model"]) == RUN_RESPONSES["dict"]


def test_get_actor_latest_build(mock_client, mock_requests):
    """The default build is fetched with the Actor object ID."""
    build = get_actor_latest_build(mock_client, ACTOR_ID)

    assert build == BUILD_RESPONSE["data"]
    mock_client.actor.assert_called_once_with(ACTOR_ID)
    url = mock_requests.request.call_args[0][1]
    assert url == "https://api.apify.com/v2/acts/actor-id/builds/default"


def test_register_actor(mock_client, mock_requests):
    """The Actor is registered as a tool with its input schema."""
    tools = ApifyTools(actors=ACTOR_ID, apify_api_token="test_token")

    assert TOOL_NAME in tools.functions
    parameters = tools.functions[TOOL_NAME].parameters
    assert set(parameters["properties"]) == {"startUrls", "maxCrawlPages"}
    assert parameters["required"] == ["startUrls"]


def test_actor_function_returns_dataset_items(mock_client, mock_requests):
    """Running the registered tool returns the items from the run's dataset."""
    tools = ApifyTools(actors=ACTOR_ID, apify_api_token="test_token")
    run_input = {"startUrls": [{"url": "https://example.com"}]}

    result = tools.functions[TOOL_NAME].entrypoint(**run_input)

    assert json.loads(result) == [{"text": "Example page"}]
    mock_client.actor.return_value.call.assert_called_once_with(run_input=run_input)
    mock_client.run.assert_called_once_with(run_id="run-id")


def test_actor_function_without_run_returns_error(mock_client, mock_requests):
    """A run that did not start is reported as an error."""
    mock_client.actor.return_value.call.return_value = None
    tools = ApifyTools(actors=ACTOR_ID, apify_api_token="test_token")

    result = tools.functions[TOOL_NAME].entrypoint(startUrls=[{"url": "https://example.com"}])

    assert "was not started properly" in json.loads(result)[0]["error"]
