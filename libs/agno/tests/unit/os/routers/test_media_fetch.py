"""Tests for the session-scoped media fetch endpoint.

Validates that GET /sessions/{session_id}/media/{storage_key}:
- returns the owner's media bytes
- isolates across users: a non-owner (and a query-param spoof) gets 404, never bytes
- enforces session membership: a key from one session can't be fetched via another
- requires authentication (401 without a valid JWT)
- admin scope bypasses isolation (by design)
- returns 503 when no media_storage is configured
- returns a clean 404 (no filesystem/bucket path leak) when the backing object is gone
- streams (does not redirect) for non-http(s) signed URLs (local backend)

And that DELETE /sessions/{session_id}?delete_media=true sweeps the session's objects out of
storage, leaves them alone unless asked, and cannot reach media the caller could not read.
"""

import glob
import os
import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from typing import Any, AsyncIterator, Iterator
from unittest.mock import AsyncMock, Mock

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media import Image
from agno.media.storage.local import LocalMediaStorage
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig

JWT_SECRET = "test-secret-for-media-fetch-min-32-bytes-long"
TEST_OS_ID = "test-media-os"
IMAGE_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake-image-payload-for-media-fetch" * 4


def create_token(user_id: str, scopes: list[str] | None = None) -> str:
    payload = {
        "sub": user_id,
        "aud": TEST_OS_ID,
        "scopes": scopes or ["agents:read", "agents:run", "sessions:read", "sessions:write"],
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


DELETE_SCOPES = ["agents:read", "agents:run", "sessions:read", "sessions:write", "sessions:delete"]


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class MockModel(Model):
    """Minimal mock model that returns a fixed text response."""

    def __init__(self):
        super().__init__(id="mock-model", name="mock-model", provider="test")
        self.instructions = None
        self._mock_response = ModelResponse(content="ok", role="assistant", response_usage=MessageMetrics())
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


@pytest.fixture
def media_dir():
    tmp = tempfile.mkdtemp(prefix="agno_media_fetch_")
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def db_file():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    for p in glob.glob(path + "*"):
        os.remove(p)


def _build(media_dir, db_file, with_storage=True):
    storage = LocalMediaStorage(base_path=media_dir)
    db = SqliteDb(db_file=db_file)
    agent = Agent(
        id="img-agent",
        model=MockModel(),
        db=db,
        media_storage=storage if with_storage else None,
        store_media=True,
    )
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[agent],
        media_storage=storage if with_storage else None,
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[JWT_SECRET], algorithm="HS256", user_isolation=True
        ),
    )
    return agent, storage, TestClient(agent_os.get_app())


def _seed(agent, user_id, session_id, content=IMAGE_BYTES):
    """Run the agent with an input image so it is offloaded + a MediaReference is persisted."""
    agent.run("describe", images=[Image(content=content, format="png")], session_id=session_id, user_id=user_id)


def _key_for(media_dir, content=IMAGE_BYTES):
    files = [f for f in glob.glob(os.path.join(media_dir, "*")) if not f.endswith(".meta.json")]
    for f in files:
        with open(f, "rb") as fh:
            if fh.read() == content:
                return os.path.basename(f)
    raise AssertionError("offloaded media file not found")


def _url(session_id, key):
    return f"/sessions/{session_id}/media/{key}?type=agent"


def test_owner_fetches_own_media(media_dir, db_file):
    agent, _, client = _build(media_dir, db_file)
    _seed(agent, "user-a", "sess-a")
    key = _key_for(media_dir)
    r = client.get(_url("sess-a", key), headers=auth_header(create_token("user-a")))
    assert r.status_code == 200
    assert r.content == IMAGE_BYTES


def test_fetch_sets_nosniff_header(media_dir, db_file):
    agent, _, client = _build(media_dir, db_file)
    _seed(agent, "user-a", "sess-a")
    key = _key_for(media_dir)
    r = client.get(_url("sess-a", key), headers=auth_header(create_token("user-a")))
    assert r.status_code == 200
    # X-Content-Type-Options: nosniff stops the browser reinterpreting the bytes as active content
    assert r.headers.get("x-content-type-options") == "nosniff"


def test_non_owner_gets_404_no_bytes(media_dir, db_file):
    agent, _, client = _build(media_dir, db_file)
    _seed(agent, "user-a", "sess-a")
    key = _key_for(media_dir)
    r = client.get(_url("sess-a", key), headers=auth_header(create_token("user-b")))
    assert r.status_code == 404
    assert r.content != IMAGE_BYTES


def test_query_param_user_spoof_is_ignored(media_dir, db_file):
    agent, _, client = _build(media_dir, db_file)
    _seed(agent, "user-a", "sess-a")
    key = _key_for(media_dir)
    # B presents B's JWT but tries ?user_id=user-a -> JWT sub must win -> 404
    r = client.get(
        f"/sessions/sess-a/media/{key}?type=agent&user_id=user-a",
        headers=auth_header(create_token("user-b")),
    )
    assert r.status_code == 404
    assert r.content != IMAGE_BYTES


def test_unauthenticated_gets_401(media_dir, db_file):
    agent, _, client = _build(media_dir, db_file)
    _seed(agent, "user-a", "sess-a")
    key = _key_for(media_dir)
    r = client.get(_url("sess-a", key))
    assert r.status_code == 401


def test_cross_session_key_reuse_blocked(media_dir, db_file):
    agent, _, client = _build(media_dir, db_file)
    _seed(agent, "user-a", "sess-a", content=IMAGE_BYTES)
    other = b"\x89PNG\r\n\x1a\n" + b"second-distinct-image" * 4
    _seed(agent, "user-a", "sess-b", content=other)
    key_a = _key_for(media_dir, IMAGE_BYTES)
    # user-a owns BOTH sessions, but the key belongs to sess-a -> fetching via sess-b 404s
    r = client.get(_url("sess-b", key_a), headers=auth_header(create_token("user-a")))
    assert r.status_code == 404


def test_no_media_storage_returns_503(media_dir, db_file):
    agent, _, client = _build(media_dir, db_file, with_storage=False)
    agent.run("hi", session_id="sess-a", user_id="user-a")
    r = client.get(_url("sess-a", "anything.png"), headers=auth_header(create_token("user-a")))
    assert r.status_code == 503


def test_admin_scope_bypasses_isolation(media_dir, db_file):
    agent, _, client = _build(media_dir, db_file)
    _seed(agent, "user-a", "sess-a")
    key = _key_for(media_dir)
    admin = create_token("admin-user", scopes=["agent_os:admin"])
    r = client.get(_url("sess-a", key), headers=auth_header(admin))
    assert r.status_code == 200
    assert r.content == IMAGE_BYTES


def test_nonexistent_key_in_owned_session_404(media_dir, db_file):
    agent, _, client = _build(media_dir, db_file)
    _seed(agent, "user-a", "sess-a")
    r = client.get(_url("sess-a", "does-not-exist.png"), headers=auth_header(create_token("user-a")))
    assert r.status_code == 404


def test_missing_backing_object_clean_404_no_path_leak(media_dir, db_file):
    agent, _, client = _build(media_dir, db_file)
    _seed(agent, "user-a", "sess-a")
    key = _key_for(media_dir)
    os.remove(os.path.join(media_dir, key))  # reference persists, backing object gone
    r = client.get(_url("sess-a", key), headers=auth_header(create_token("user-a")))
    assert r.status_code == 404
    assert media_dir not in r.text and "Errno" not in r.text  # no filesystem path leak


def test_redirect_local_streams_instead_of_file_url(media_dir, db_file):
    agent, _, client = _build(media_dir, db_file)
    _seed(agent, "user-a", "sess-a")
    key = _key_for(media_dir)
    r = client.get(
        f"/sessions/sess-a/media/{key}?type=agent&redirect=true",
        headers=auth_header(create_token("user-a")),
        follow_redirects=False,
    )
    # local backend would redirect to file:// (useless to a browser) -> we stream instead
    assert r.status_code == 200
    assert r.content == IMAGE_BYTES


def test_reference_from_another_backend_404s(media_dir, db_file):
    """A reference stamped with a different storage_backend must not be served from the
    configured one: a same-named object in the wrong bucket would otherwise be handed back."""
    agent, _, client = _build(media_dir, db_file)
    _seed(agent, "user-a", "sess-a")
    key = _key_for(media_dir)

    session = agent.get_session(session_id="sess-a", user_id="user-a")
    for media in session.runs[0].input.images:
        media.media_reference.storage_backend = "s3"
    agent.db.upsert_session(session)
    # Runs live in the runs table since the sessions-table denormalization, so the
    # mutated reference must be persisted on the run row as well.
    agent.db.upsert_run(run=session.runs[0], session_id="sess-a", user_id="user-a")

    r = client.get(_url("sess-a", key), headers=auth_header(create_token("user-a")))
    assert r.status_code == 404
    assert r.content != IMAGE_BYTES


def test_stored_url_is_never_redirected_to(media_dir, db_file):
    """The url on a reference is an opaque stored string that only has to look like a link, so
    honouring it on redirect=true would turn this route into an open redirect. The url is
    always re-derived from the storage_key that was just checked against the session."""
    agent, _, client = _build(media_dir, db_file)
    _seed(agent, "user-a", "sess-a")
    key = _key_for(media_dir)

    session = agent.get_session(session_id="sess-a", user_id="user-a")
    for media in session.runs[0].input.images:
        media.media_reference.url = "https://evil.example.com/pwned"
    agent.db.upsert_session(session)
    agent.db.upsert_run(run=session.runs[0], session_id="sess-a", user_id="user-a")

    r = client.get(
        f"/sessions/sess-a/media/{key}?type=agent&redirect=true",
        headers=auth_header(create_token("user-a")),
        follow_redirects=False,
    )
    assert r.status_code == 200
    assert "evil.example.com" not in r.headers.get("location", "")
    assert r.content == IMAGE_BYTES


def test_owner_deletes_the_session_and_its_media(media_dir, db_file):
    """The objects outlive the rows that name them, so deleting a session leaves them
    unreachable forever unless the caller asks for them to go too."""
    agent, storage, client = _build(media_dir, db_file)
    _seed(agent, "user-a", "sess-a")
    key = _key_for(media_dir)

    r = client.delete("/sessions/sess-a?delete_media=true", headers=auth_header(create_token("user-a", DELETE_SCOPES)))

    assert r.status_code == 204
    assert storage.exists(key) is False
    assert agent.get_session(session_id="sess-a", user_id="user-a") is None


def test_delete_leaves_media_alone_by_default(media_dir, db_file):
    agent, storage, client = _build(media_dir, db_file)
    _seed(agent, "user-a", "sess-a")
    key = _key_for(media_dir)

    r = client.delete("/sessions/sess-a", headers=auth_header(create_token("user-a", DELETE_SCOPES)))

    assert r.status_code == 204
    assert storage.exists(key) is True


def test_non_owner_cannot_delete_another_users_media(media_dir, db_file):
    """The sweep runs on sessions resolved for the caller, so it cannot reach media the
    caller could not read in the first place."""
    agent, storage, client = _build(media_dir, db_file)
    _seed(agent, "user-a", "sess-a")
    key = _key_for(media_dir)

    client.delete("/sessions/sess-a?delete_media=true", headers=auth_header(create_token("user-b", DELETE_SCOPES)))

    assert storage.exists(key) is True
    assert agent.get_session(session_id="sess-a", user_id="user-a") is not None


def test_delete_media_without_a_backend_is_refused(media_dir, db_file):
    agent, _, client = _build(media_dir, db_file, with_storage=False)
    _seed(agent, "user-a", "sess-a")

    r = client.delete("/sessions/sess-a?delete_media=true", headers=auth_header(create_token("user-a", DELETE_SCOPES)))

    assert r.status_code == 503
    assert agent.get_session(session_id="sess-a", user_id="user-a") is not None
