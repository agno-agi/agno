import json
import time
from unittest.mock import MagicMock, patch

import pytest

from agno.storage.gcs_json import GCSJsonStorage
from agno.storage.session.agent import AgentSession


# Fixture to mock the GCS client and bucket
@pytest.fixture
def mock_gcs_client():
    with patch("agno.storage.gcs_json.gcs.Client") as MockClient:
        client_instance = MagicMock()
        MockClient.return_value = client_instance

        # Create a mock bucket
        bucket = MagicMock()
        # For testing, simulate that the bucket already exists.
        bucket.exists.return_value = True
        client_instance.bucket.return_value = bucket

        yield client_instance, bucket


# Fixture to instantiate GCSJsonStorage with the mocked GCS client
@pytest.fixture
def gcs_storage(mock_gcs_client):
    client_instance, bucket = mock_gcs_client
    # Use dummy bucket name and project
    storage = GCSJsonStorage(
        bucket_name="dummy-bucket",
        prefix="agent/",
        project="dummy-project",
        location="dummy-location",
        credentials=None,  # Pass None to avoid real authentication
        mode="agent",
    )
    # Inject our mocked client and bucket into the instance
    storage.client = client_instance
    storage.bucket = bucket
    yield storage


def test_upsert_and_read_agent(gcs_storage):
    # Create a dummy AgentSession
    session = AgentSession(
        session_id="test-session",
        agent_id="agent-1",
        user_id="user-1",
        memory={"data": "value"},
        agent_data={"name": "Test Agent"},
        session_data={"state": "active"},
        extra_data={"custom": "data"},
    )
    # Prepare a mock blob
    blob = MagicMock()
    gcs_storage.bucket.blob.return_value = blob

    # Test upsert: it should call blob.upload_from_string with the session's JSON
    result = gcs_storage.upsert(session)
    assert result == session
    blob.upload_from_string.assert_called_once()

    # Prepare a JSON string to simulate a successful read.
    session_dict = session.to_dict()
    session_dict["updated_at"] = int(time.time())
    if "created_at" not in session_dict:
        session_dict["created_at"] = session_dict["updated_at"]
    json_data = json.dumps(session_dict, ensure_ascii=False, indent=4)
    blob.download_as_bytes.return_value = json_data.encode("utf-8")

    read_session = gcs_storage.read("test-session")
    assert read_session is not None
    assert read_session.session_id == session.session_id


def test_read_not_found(gcs_storage):
    # Simulate the blob for a non-existent session that raises an exception
    blob = MagicMock()
    gcs_storage.bucket.blob.return_value = blob
    blob.download_as_bytes.side_effect = Exception("404 Not Found")

    result = gcs_storage.read("non-existent-session")
    assert result is None


def test_get_all_session_ids(gcs_storage):
    # Simulate listing blobs that return two sessions
    blob1 = MagicMock()
    blob1.name = "session-1.json"
    blob2 = MagicMock()
    blob2.name = "session-2.json"
    gcs_storage.client.list_blobs.return_value = [blob1, blob2]

    session_ids = gcs_storage.get_all_session_ids()
    assert session_ids == ["session-1", "session-2"]


def test_delete_session(gcs_storage):
    # Prepare a mock blob for deletion
    blob = MagicMock()
    gcs_storage.bucket.blob.return_value = blob

    gcs_storage.delete_session("test-session")
    blob.delete.assert_called_once()
