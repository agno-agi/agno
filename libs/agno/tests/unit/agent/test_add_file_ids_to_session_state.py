"""Tests for the add_file_ids_to_session_state Agent option.

Verifies https://github.com/agno-agi/agno/issues/7306 —
when enabled, references (id and name/filename) of the media provided with the
run input are recorded in session_state, so tools can discover them even when
the media itself is not sent to the model (send_media_to_model=False).
Only references are stored, never the media content.
"""

from typing import Any, AsyncIterator, Iterator
from unittest.mock import AsyncMock, Mock

import pytest

from agno.agent._messages import _add_media_ids_to_session_state
from agno.agent.agent import Agent
from agno.media import Audio, File, Image, Video
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.run import RunContext


class MockModel(Model):
    def __init__(self):
        super().__init__(id="test-model", name="test-model", provider="test")
        self.instructions = None

        self._mock_response = ModelResponse(
            content="Done",
            role="assistant",
            response_usage=MessageMetrics(),
        )

        self.response = Mock(return_value=self._mock_response)
        self.aresponse = AsyncMock(return_value=self._mock_response)

    def get_instructions_for_model(self, *args, **kwargs):
        return None

    def get_system_message_for_model(self, *args, **kwargs):
        return None

    async def aget_instructions_for_model(self, *args, **kwargs):
        return None

    async def aget_system_message_for_model(self, *args, **kwargs):
        return None

    def parse_args(self, *args, **kwargs):
        return {}

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._mock_response

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return await self.aresponse(*args, **kwargs)

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._mock_response

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._mock_response
        return

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return self._mock_response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._mock_response


def test_disabled_by_default_does_not_record_media():
    """With the default (flag off), session_state must not be modified."""
    agent = Agent(model=MockModel())

    result = agent.run(
        "Process this file",
        files=[File(url="https://example.com/report.csv", id="file-1", filename="report.csv")],
        images=[Image(url="https://example.com/chart.png", id="img-1")],
    )

    assert result.session_state is not None
    assert "files" not in result.session_state
    assert "images" not in result.session_state


def test_records_media_references_sync():
    """Flag on: ids and names of all input media types are recorded in session_state."""
    agent = Agent(model=MockModel(), add_file_ids_to_session_state=True)

    result = agent.run(
        "Process these",
        images=[Image(url="https://example.com/chart.png", id="img-1")],
        videos=[Video(url="https://example.com/clip.mp4", id="vid-1")],
        audio=[Audio(url="https://example.com/voice.mp3", id="aud-1")],
        files=[File(url="https://example.com/report.csv", id="file-1", filename="report.csv")],
    )

    assert result.session_state is not None
    assert result.session_state["images"] == [{"id": "img-1"}]
    assert result.session_state["videos"] == [{"id": "vid-1"}]
    assert result.session_state["audios"] == [{"id": "aud-1"}]
    assert result.session_state["files"] == [{"id": "file-1", "name": "report.csv"}]


def test_generates_id_for_media_without_id():
    """Media without an id gets one assigned, so the session_state reference is usable."""
    agent = Agent(model=MockModel(), add_file_ids_to_session_state=True)
    upload = File(url="https://example.com/data.xls", filename="data.xls")

    result = agent.run("Process this file", files=[upload])

    assert upload.id is not None
    assert result.session_state is not None
    assert result.session_state["files"] == [{"id": upload.id, "name": "data.xls"}]


@pytest.mark.asyncio
async def test_records_media_references_async():
    """Async path: ids are recorded in session_state as well."""
    agent = Agent(model=MockModel(), add_file_ids_to_session_state=True)

    result = await agent.arun(
        "Process this file",
        files=[File(url="https://example.com/report.csv", id="file-1", filename="report.csv")],
    )

    assert result.session_state is not None
    assert result.session_state["files"] == [{"id": "file-1", "name": "report.csv"}]


def test_appends_and_dedupes_across_runs():
    """Existing entries are kept, known ids are not duplicated, new media is appended."""
    agent = Agent(model=MockModel(), add_file_ids_to_session_state=True)
    session_state = {"files": [{"id": "file-1", "name": "first.csv"}]}

    result = agent.run(
        "Process these files",
        files=[
            File(url="https://example.com/first.csv", id="file-1", filename="first.csv"),
            File(url="https://example.com/second.csv", id="file-2", filename="second.csv"),
        ],
        session_state=session_state,
    )

    assert result.session_state is not None
    assert result.session_state["files"] == [
        {"id": "file-1", "name": "first.csv"},
        {"id": "file-2", "name": "second.csv"},
    ]


def test_preserves_existing_session_state_keys():
    """Recording media references must not clobber unrelated session_state keys."""
    agent = Agent(model=MockModel(), add_file_ids_to_session_state=True)

    result = agent.run(
        "Process this file",
        files=[File(url="https://example.com/report.csv", id="file-1", filename="report.csv")],
        session_state={"customer_id": "cust-123"},
    )

    assert result.session_state is not None
    assert result.session_state["customer_id"] == "cust-123"
    assert result.session_state["files"] == [{"id": "file-1", "name": "report.csv"}]


def test_records_media_when_not_sent_to_model():
    """The issue scenario: send_media_to_model=False, tools still learn about the file."""
    agent = Agent(model=MockModel(), send_media_to_model=False, add_file_ids_to_session_state=True)

    result = agent.run(
        "Sum the columns in this spreadsheet",
        files=[File(url="https://example.com/data.xls", id="file-1", filename="data.xls")],
    )

    assert result.session_state is not None
    assert result.session_state["files"] == [{"id": "file-1", "name": "data.xls"}]


def test_serialization_round_trip():
    """The flag survives to_dict/from_dict so stored agents keep the behavior."""
    agent = Agent(model=MockModel(), add_file_ids_to_session_state=True)

    config = agent.to_dict()
    assert config["add_file_ids_to_session_state"] is True

    # The mock model provider is not a registered provider, so drop it before rebuilding
    config.pop("model", None)
    restored = Agent.from_dict(config)
    assert restored.add_file_ids_to_session_state is True

    # Default agents don't serialize the flag and restore it as False
    default_config = Agent(model=MockModel()).to_dict()
    assert "add_file_ids_to_session_state" not in default_config
    default_config.pop("model", None)
    assert Agent.from_dict(default_config).add_file_ids_to_session_state is False


def test_helper_initializes_none_session_state():
    """The helper works on a bare RunContext whose session_state is None."""
    run_context = RunContext(run_id="r1", session_id="s1")

    _add_media_ids_to_session_state(
        run_context,
        files=[File(url="https://example.com/report.csv", id="file-1", filename="report.csv")],
    )

    assert run_context.session_state is not None
    assert run_context.session_state["files"] == [{"id": "file-1", "name": "report.csv"}]


def test_helper_replaces_non_list_existing_value():
    """A pre-existing non-list value under a media key is replaced, not corrupted."""
    run_context = RunContext(run_id="r1", session_id="s1", session_state={"files": "stale-value"})

    _add_media_ids_to_session_state(
        run_context,
        files=[File(url="https://example.com/report.csv", id="file-1", filename="report.csv")],
    )

    assert run_context.session_state["files"] == [{"id": "file-1", "name": "report.csv"}]


def test_helper_ignores_empty_media():
    """No media input leaves session_state untouched."""
    run_context = RunContext(run_id="r1", session_id="s1", session_state={"customer_id": "cust-123"})

    _add_media_ids_to_session_state(run_context)

    assert run_context.session_state == {"customer_id": "cust-123"}
