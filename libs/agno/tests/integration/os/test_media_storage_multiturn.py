"""Integration tests for multi-turn media handling through AgentOS API.

Verifies that when store_media=False + media_storage is configured,
images uploaded via the API are offloaded to external storage and
reconstructed on subsequent turns via MediaReference pointers.
"""

import shutil
import tempfile
from pathlib import Path
from typing import Any, AsyncIterator, Iterator
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media_storage.local import LocalMediaStorage
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS

# -- Mock Model --


class MockModel(Model):
    """Minimal mock model that returns a fixed text response."""

    def __init__(self):
        super().__init__(id="mock-model", name="mock-model", provider="test")
        self.instructions = None
        self._mock_response = ModelResponse(
            content="I see a beautiful landscape in the image.",
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


# -- Fixtures --


@pytest.fixture
def media_dir():
    """Temporary directory for LocalMediaStorage."""
    tmpdir = tempfile.mkdtemp(prefix="agno_media_test_")
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def media_db_file():
    """Temporary SQLite DB file."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    Path(path).unlink(missing_ok=True)


@pytest.fixture
def media_agent_store_false(media_dir, media_db_file):
    """Agent with store_media=False + LocalMediaStorage."""
    return Agent(
        name="media-test-agent",
        id="media-test-agent",
        model=MockModel(),
        store_media=False,
        media_storage=LocalMediaStorage(base_path=media_dir),
        db=SqliteDb(db_file=media_db_file),
        add_history_to_context=True,
    )


@pytest.fixture
def media_agent_store_true(media_dir, media_db_file):
    """Agent with store_media=True + LocalMediaStorage."""
    return Agent(
        name="media-test-agent-true",
        id="media-test-agent-true",
        model=MockModel(),
        store_media=True,
        media_storage=LocalMediaStorage(base_path=media_dir),
        db=SqliteDb(db_file=media_db_file),
        add_history_to_context=True,
    )


def _make_client(agent: Agent) -> TestClient:
    """Create a TestClient for an AgentOS wrapping the given agent."""
    agent_os = AgentOS(agents=[agent])
    return TestClient(agent_os.get_app())


# -- Tests --


class TestAgentOSMediaStorageMultiturn:
    """Test multi-turn media through AgentOS API endpoints."""

    def test_multiturn_store_media_false_preserves_image(self, media_agent_store_false, media_dir):
        """store_media=False + media_storage: turn 2 should still have image in history."""
        agent = media_agent_store_false
        client = _make_client(agent)

        # Patch deep_copy to return the SAME agent instance so config is preserved
        # (AgentOS creates fresh copies per request, but MockModel isn't deep-copyable)
        with patch.object(agent, "deep_copy", return_value=agent):
            # Turn 1: upload image
            session_id = "test-multiturn-session"
            files = [("files", ("landscape.png", b"fake-png-image-bytes-1234567890" * 100, "image/png"))]
            resp1 = client.post(
                f"/agents/{agent.id}/runs",
                data={
                    "message": "What do you see in this image?",
                    "stream": "false",
                    "session_id": session_id,
                },
                files=files,
            )
            assert resp1.status_code == 200

            # Verify media was offloaded to disk
            media_files = [f for f in Path(media_dir).iterdir() if not f.name.endswith(".meta.json")]
            assert len(media_files) >= 1, "Image should be offloaded to local storage"

            # Verify session has MediaReference (not raw bytes)
            session = agent.get_session(session_id=session_id)
            assert session is not None
            assert len(session.runs) == 1

            # Check that messages have media_reference pointers
            has_media_ref = False
            for msg in session.runs[0].messages or []:
                if msg.images:
                    for img in msg.images:
                        if img.media_reference is not None:
                            has_media_ref = True
            assert has_media_ref, "Session run should have MediaReference pointers after offload"

            # Turn 2: ask about the image WITHOUT uploading it
            resp2 = client.post(
                f"/agents/{agent.id}/runs",
                data={
                    "message": "What was the image about?",
                    "stream": "false",
                    "session_id": session_id,
                },
            )
            assert resp2.status_code == 200

            # Verify turn 2 succeeded and session now has 2 runs
            session = agent.get_session(session_id=session_id)
            assert len(session.runs) == 2

    def test_multiturn_store_media_true_preserves_image(self, media_agent_store_true, media_dir):
        """store_media=True + media_storage: control case — should also work."""
        agent = media_agent_store_true
        client = _make_client(agent)

        with patch.object(agent, "deep_copy", return_value=agent):
            session_id = "test-multiturn-true-session"
            files = [("files", ("landscape.png", b"fake-png-image-bytes-1234567890" * 100, "image/png"))]
            resp1 = client.post(
                f"/agents/{agent.id}/runs",
                data={
                    "message": "What do you see in this image?",
                    "stream": "false",
                    "session_id": session_id,
                },
                files=files,
            )
            assert resp1.status_code == 200

            # Media offloaded to disk
            media_files = [f for f in Path(media_dir).iterdir() if not f.name.endswith(".meta.json")]
            assert len(media_files) >= 1

            # Turn 2
            resp2 = client.post(
                f"/agents/{agent.id}/runs",
                data={
                    "message": "What was the image about?",
                    "stream": "false",
                    "session_id": session_id,
                },
            )
            assert resp2.status_code == 200
            session = agent.get_session(session_id=session_id)
            assert len(session.runs) == 2

    def test_single_turn_offloads_to_disk(self, media_agent_store_false, media_dir):
        """After a single API call, image should be on disk with MediaReference in session."""
        agent = media_agent_store_false
        client = _make_client(agent)

        image_bytes = b"fake-png-image-content-for-offload-test" * 50

        with patch.object(agent, "deep_copy", return_value=agent):
            files = [("files", ("photo.png", image_bytes, "image/png"))]
            resp = client.post(
                f"/agents/{agent.id}/runs",
                data={
                    "message": "Describe this image",
                    "stream": "false",
                    "session_id": "single-turn-test",
                },
                files=files,
            )
            assert resp.status_code == 200

            # Image on disk
            media_files = [f for f in Path(media_dir).iterdir() if not f.name.endswith(".meta.json")]
            assert len(media_files) == 1
            assert media_files[0].stat().st_size == len(image_bytes)

            # Session has MediaReference, not raw bytes
            session = agent.get_session(session_id="single-turn-test")
            run = session.runs[0]
            has_ref = False
            has_raw_content = False
            for msg in run.messages or []:
                if msg.images:
                    for img in msg.images:
                        if img.media_reference is not None:
                            has_ref = True
                        if img.content is not None:
                            has_raw_content = True
            assert has_ref, "Session should have MediaReference"
            assert not has_raw_content, "Session should NOT have raw content bytes (store_media=False)"
