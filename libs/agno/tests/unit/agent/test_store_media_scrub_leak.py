"""Reproduction tests for media leak through scrub_media_from_run_output.

These tests prove that scrub_media_from_run_output() must null top-level
output media fields (images/videos/audio/files), not just input/message media.

Without the fix, member responses and workflow executor runs leak media to DB
when the member/executor has store_media=False.
"""

from typing import Any, AsyncIterator, Iterator
from unittest.mock import AsyncMock, Mock

import pytest

from agno.agent.agent import Agent
from agno.media import Image, Video
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.utils.agent import scrub_media_from_run_output


class MockModelWithImage(Model):
    def __init__(self):
        super().__init__(id="test-model", name="test-model", provider="test")
        self.instructions = None

        self._mock_response = ModelResponse(
            content="Here is your generated image",
            role="assistant",
            images=[Image(url="https://example.com/generated.png", id="img-1")],
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


# -- Core scrub function tests --


def test_scrub_media_nulls_top_level_output_images():
    """scrub_media_from_run_output must null run_response.images."""
    run_output = RunOutput(
        images=[Image(url="https://example.com/img.png", id="img-1")],
    )
    scrub_media_from_run_output(run_output)
    assert run_output.images is None, "images should be None after scrub"


def test_scrub_media_nulls_top_level_output_videos():
    """scrub_media_from_run_output must null run_response.videos."""
    run_output = RunOutput(
        videos=[Video(url="https://example.com/vid.mp4", id="vid-1")],
    )
    scrub_media_from_run_output(run_output)
    assert run_output.videos is None, "videos should be None after scrub"


def test_scrub_media_nulls_top_level_output_audio():
    """scrub_media_from_run_output must null run_response.audio."""
    from agno.media import Audio

    run_output = RunOutput(
        audio=[Audio(id="aud-1", content=b"fake-audio")],
    )
    scrub_media_from_run_output(run_output)
    assert run_output.audio is None, "audio should be None after scrub"


def test_scrub_media_nulls_top_level_output_files():
    """scrub_media_from_run_output must null run_response.files."""
    from agno.media import File

    run_output = RunOutput(
        files=[File(id="file-1", content=b"fake-file")],
    )
    scrub_media_from_run_output(run_output)
    assert run_output.files is None, "files should be None after scrub"


def test_scrub_media_nulls_team_run_output_images():
    """scrub_media_from_run_output works on TeamRunOutput too."""
    team_output = TeamRunOutput(
        images=[Image(url="https://example.com/img.png", id="img-1")],
    )
    scrub_media_from_run_output(team_output)
    assert team_output.images is None, "TeamRunOutput.images should be None after scrub"


# -- Member response leak reproduction --


def test_member_response_media_scrubbed_via_scrub_run_output_for_storage():
    """Simulates _scrub_member_responses path: scrub_run_output_for_storage
    must clear top-level images on a member response when store_media=False."""
    from agno.agent._run import scrub_run_output_for_storage

    member_agent = Agent(model=MockModelWithImage(), store_media=False)

    # Simulate a member response with generated images
    member_response = RunOutput(
        agent_id=member_agent.id,
        images=[Image(url="https://example.com/generated.png", id="img-1")],
        content="Here is your image",
    )

    scrub_run_output_for_storage(member_agent, member_response)

    assert member_response.images is None, (
        "Member response images should be None after scrub_run_output_for_storage "
        "with store_media=False. Without this fix, images leak to DB."
    )


def test_member_response_media_preserved_when_store_media_true():
    """When store_media=True, scrub_run_output_for_storage should NOT be called
    for media, so images remain."""
    from agno.agent._run import scrub_run_output_for_storage

    member_agent = Agent(model=MockModelWithImage(), store_media=True)

    member_response = RunOutput(
        agent_id=member_agent.id,
        images=[Image(url="https://example.com/generated.png", id="img-1")],
        content="Here is your image",
    )

    scrub_run_output_for_storage(member_agent, member_response)

    # store_media=True means scrub_media_from_run_output is NOT called
    assert member_response.images is not None
    assert len(member_response.images) == 1


# -- Agent cleanup save/restore still works --


def test_cleanup_and_store_restores_media_after_scrub():
    """cleanup_and_store saves media before scrub and restores in finally.
    Even with the fix to scrub_media_from_run_output, the caller must
    still get images back."""
    agent = Agent(model=MockModelWithImage(), store_media=False)

    result = agent.run("Generate an image")

    assert result.images is not None, "Caller should see images after cleanup_and_store"
    assert len(result.images) == 1
    assert result.images[0].url == "https://example.com/generated.png"


@pytest.mark.asyncio
async def test_acleanup_and_store_restores_media_after_scrub():
    """Async variant: caller still gets images back."""
    agent = Agent(model=MockModelWithImage(), store_media=False)

    result = await agent.arun("Generate an image")

    assert result.images is not None, "Caller should see images after acleanup_and_store"
    assert len(result.images) == 1
    assert result.images[0].url == "https://example.com/generated.png"


# -- Session cache isolation --


def test_session_cache_does_not_have_media_when_store_media_false():
    """After agent.run with store_media=False, the session's cached run
    should NOT have images — only the returned RunOutput should."""
    agent = Agent(model=MockModelWithImage(), store_media=False)

    result = agent.run("Generate an image")

    # Caller sees images
    assert result.images is not None

    # Session cache should NOT have images
    session = agent.get_session()
    if session and session.runs:
        for run in session.runs:
            assert run.images is None, "Session cached run should not have images when store_media=False"
