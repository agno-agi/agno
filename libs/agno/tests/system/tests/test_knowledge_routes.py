"""
System Tests for AgentOS Knowledge Routes.

Run with: pytest test_knowledge_routes.py -v --tb=short
"""

import time
import uuid

import httpx
import pytest

from .test_utils import REQUEST_TIMEOUT, generate_jwt_token


@pytest.fixture(scope="module")
def test_user_id() -> str:
    """Generate a unique user ID for testing."""
    return f"test-user-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def client(gateway_url: str, test_user_id: str) -> httpx.Client:
    """Create an HTTP client for the gateway server with authentication."""
    return httpx.Client(
        base_url=gateway_url,
        timeout=REQUEST_TIMEOUT,
        headers={"Authorization": f"Bearer {generate_jwt_token(audience='gateway-os', user_id=test_user_id)}"},
    )


# =============================================================================
# Knowledge Routes Tests
# =============================================================================


def clear_all_knowledge_content(client: httpx.Client, db_id: str) -> None:
    """Clear all knowledge content from the database.

    Args:
        client: HTTP client
        db_id: Database ID to clear content from
    """
    client.delete(f"/knowledge/content?db_id={db_id}")
    # It's okay if this fails - we'll continue with tests


class TestLocalKnowledgeRoutes:
    """Test knowledge routes with local database (gateway-db)."""

    DB_ID = "gateway-db"
    CONTENT_NAME = "Local Test Document"
    CONTENT_TEXT = "This is local test content about AgentOS framework. It covers system testing, integration patterns, best practices for agent development, and Python programming."

    @pytest.fixture(scope="class", autouse=True)
    def setup_knowledge_content(self, client: httpx.Client) -> dict:
        """Set up knowledge content before running tests."""
        # Clear existing content first
        clear_all_knowledge_content(client, self.DB_ID)

        # Upload test content
        unique_name = f"{self.CONTENT_NAME} {uuid.uuid4().hex[:8]}"
        response = client.post(
            f"/knowledge/content?db_id={self.DB_ID}",
            data={
                "name": unique_name,
                "description": "A comprehensive test document for local knowledge testing",
                "text_content": self.CONTENT_TEXT,
            },
        )
        assert response.status_code == 202
        data = response.json()

        # Wait for content to be processed
        time.sleep(3)

        return {
            "content_id": data.get("id"),
            "name": unique_name,
        }

    def test_get_knowledge_config_structure(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test GET /knowledge/config returns complete configuration."""
        response = client.get(f"/knowledge/config?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "readers" in data
        assert "chunkers" in data
        assert "readersForType" in data

        if data["readers"]:
            reader_key = list(data["readers"].keys())[0]
            reader = data["readers"][reader_key]
            assert "id" in reader
            assert "name" in reader

        if data["chunkers"]:
            chunker_key = list(data["chunkers"].keys())[0]
            chunker = data["chunkers"][chunker_key]
            assert "key" in chunker
            assert "name" in chunker

    def test_get_knowledge_content_paginated(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test GET /knowledge/content returns paginated content list including our uploaded content."""
        response = client.get(f"/knowledge/content?limit=10&page=1&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        assert "meta" in data
        assert isinstance(data["data"], list)
        assert len(data["data"]) >= 1

        # Verify our content is in the list
        content_ids = [c["id"] for c in data["data"]]
        assert setup_knowledge_content["content_id"] in content_ids

        meta = data["meta"]
        assert "page" in meta
        assert "limit" in meta

    def test_get_content_by_id(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test GET /knowledge/content/{content_id} returns content details."""
        content_id = setup_knowledge_content["content_id"]
        response = client.get(f"/knowledge/content/{content_id}?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert data["id"] == content_id
        assert data["name"] == setup_knowledge_content["name"]
        assert "status" in data
        assert "created_at" in data

    def test_get_content_status(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test GET /knowledge/content/{content_id}/status returns processing status."""
        content_id = setup_knowledge_content["content_id"]
        response = client.get(f"/knowledge/content/{content_id}/status?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "status" in data
        # Status should be either processing or completed
        assert data["status"] in ["processing", "completed", "ready"]

    def test_upload_additional_text_content(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test POST /knowledge/content returns content ID for additional content."""
        unique_name = f"Additional Local Document {uuid.uuid4().hex[:8]}"
        response = client.post(
            f"/knowledge/content?db_id={self.DB_ID}",
            data={
                "name": unique_name,
                "description": "An additional test document",
                "text_content": "Additional content about machine learning, AI agents, and natural language processing.",
            },
        )
        assert response.status_code == 202
        data = response.json()

        assert "id" in data
        assert data["name"] == unique_name
        assert data["status"] == "processing"

    def test_search_knowledge_returns_results(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test POST /knowledge/search returns structured results matching our content."""
        response = client.post(
            "/knowledge/search",
            json={
                "query": "AgentOS framework testing",
                "max_results": 10,
                "db_id": self.DB_ID,
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        assert "meta" in data
        assert isinstance(data["data"], list)
        # Should find our uploaded content
        assert len(data["data"]) >= 1

    def test_search_knowledge_with_specific_query(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test POST /knowledge/search with specific query terms."""
        response = client.post(
            "/knowledge/search",
            json={
                "query": "Python programming best practices",
                "max_results": 5,
                "db_id": self.DB_ID,
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        assert isinstance(data["data"], list)

    def test_update_content_metadata(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test PATCH /knowledge/content/{content_id} updates content metadata."""
        content_id = setup_knowledge_content["content_id"]
        new_name = f"Updated Local Document {uuid.uuid4().hex[:8]}"

        response = client.patch(
            f"/knowledge/content/{content_id}?db_id={self.DB_ID}",
            data={
                "name": new_name,
                "description": "Updated description for the test document",
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert data["name"] == new_name

    def test_delete_content(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test DELETE /knowledge/content/{content_id} removes specific content."""
        # Create a new content to delete
        unique_name = f"Content To Delete {uuid.uuid4().hex[:8]}"
        create_response = client.post(
            f"/knowledge/content?db_id={self.DB_ID}",
            data={
                "name": unique_name,
                "description": "Content that will be deleted",
                "text_content": "This content is meant to be deleted during testing.",
            },
        )
        assert create_response.status_code == 202
        content_id = create_response.json()["id"]

        # Delete it
        delete_response = client.delete(f"/knowledge/content/{content_id}?db_id={self.DB_ID}")
        assert delete_response.status_code == 200

        # Verify it's gone
        verify_response = client.get(f"/knowledge/content/{content_id}?db_id={self.DB_ID}")
        assert verify_response.status_code == 404


class TestRemoteKnowledgeRoutes:
    """Test knowledge routes with remote database (remote-db)."""

    DB_ID = "remote-db"
    CONTENT_NAME = "Remote Test Document"
    CONTENT_TEXT = "This is remote test content about distributed systems. It covers microservices, API design, cloud architecture, and scalable applications."

    @pytest.fixture(scope="class", autouse=True)
    def setup_knowledge_content(self, client: httpx.Client) -> dict:
        """Set up knowledge content before running tests."""
        # Clear existing content first
        clear_all_knowledge_content(client, self.DB_ID)

        # Upload test content
        unique_name = f"{self.CONTENT_NAME} {uuid.uuid4().hex[:8]}"
        response = client.post(
            f"/knowledge/content?db_id={self.DB_ID}",
            data={
                "name": unique_name,
                "description": "A comprehensive test document for remote knowledge testing",
                "text_content": self.CONTENT_TEXT,
            },
        )
        assert response.status_code == 202
        data = response.json()

        # Wait for content to be processed
        time.sleep(3)

        return {
            "content_id": data.get("id"),
            "name": unique_name,
        }

    def test_get_knowledge_config_structure(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test GET /knowledge/config returns complete configuration for remote db."""
        response = client.get(f"/knowledge/config?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "readers" in data
        assert "chunkers" in data
        assert "readersForType" in data

    def test_get_knowledge_content_paginated(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test GET /knowledge/content returns paginated content list for remote db."""
        response = client.get(f"/knowledge/content?limit=10&page=1&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        assert "meta" in data
        assert isinstance(data["data"], list)
        assert len(data["data"]) >= 1

        # Verify our content is in the list
        content_ids = [c["id"] for c in data["data"]]
        assert setup_knowledge_content["content_id"] in content_ids

    def test_get_content_by_id(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test GET /knowledge/content/{content_id} returns content details for remote db."""
        content_id = setup_knowledge_content["content_id"]
        response = client.get(f"/knowledge/content/{content_id}?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert data["id"] == content_id
        assert data["name"] == setup_knowledge_content["name"]

    def test_get_content_status(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test GET /knowledge/content/{content_id}/status returns processing status for remote db."""
        content_id = setup_knowledge_content["content_id"]
        response = client.get(f"/knowledge/content/{content_id}/status?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "status" in data

    def test_upload_additional_text_content(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test POST /knowledge/content uploads additional content for remote db."""
        unique_name = f"Additional Remote Document {uuid.uuid4().hex[:8]}"
        response = client.post(
            f"/knowledge/content?db_id={self.DB_ID}",
            data={
                "name": unique_name,
                "description": "An additional remote test document",
                "text_content": "Additional content about Kubernetes, Docker containers, and container orchestration.",
            },
        )
        assert response.status_code == 202
        data = response.json()

        assert "id" in data
        assert data["name"] == unique_name
        assert data["status"] == "processing"

    def test_search_knowledge_returns_results(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test POST /knowledge/search returns results for remote db."""
        response = client.post(
            "/knowledge/search",
            json={
                "query": "distributed systems microservices",
                "max_results": 10,
                "db_id": self.DB_ID,
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        assert "meta" in data
        assert isinstance(data["data"], list)
        # Should find our uploaded content
        assert len(data["data"]) >= 1

    def test_search_knowledge_with_specific_query(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test POST /knowledge/search with specific query terms for remote db."""
        response = client.post(
            "/knowledge/search",
            json={
                "query": "cloud architecture scalable",
                "max_results": 5,
                "db_id": self.DB_ID,
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        assert isinstance(data["data"], list)

    def test_update_content_metadata(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test PATCH /knowledge/content/{content_id} updates content metadata for remote db."""
        content_id = setup_knowledge_content["content_id"]
        new_name = f"Updated Remote Document {uuid.uuid4().hex[:8]}"

        response = client.patch(
            f"/knowledge/content/{content_id}?db_id={self.DB_ID}",
            data={
                "name": new_name,
                "description": "Updated description for the remote test document",
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert data["name"] == new_name

    def test_delete_content(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test DELETE /knowledge/content/{content_id} removes specific content for remote db."""
        # Create a new content to delete
        unique_name = f"Remote Content To Delete {uuid.uuid4().hex[:8]}"
        create_response = client.post(
            f"/knowledge/content?db_id={self.DB_ID}",
            data={
                "name": unique_name,
                "description": "Remote content that will be deleted",
                "text_content": "This remote content is meant to be deleted during testing.",
            },
        )
        assert create_response.status_code == 202
        content_id = create_response.json()["id"]

        # Delete it
        delete_response = client.delete(f"/knowledge/content/{content_id}?db_id={self.DB_ID}")
        assert delete_response.status_code == 200

        # Verify it's gone
        verify_response = client.get(f"/knowledge/content/{content_id}?db_id={self.DB_ID}")
        assert verify_response.status_code == 404


# =============================================================================
# Remote Content Endpoint Tests
# =============================================================================


class TestRemoteContentEndpoint:
    """Test remote content upload endpoint structure and validation.

    Note: These tests verify endpoint behavior without requiring actual
    remote content sources (GitHub, SharePoint, S3, GCS) to be configured.
    They test validation, error handling, and response structure.
    """

    DB_ID = "gateway-db"

    def test_config_includes_remote_content_sources_field(self, client: httpx.Client):
        """Test GET /knowledge/config includes remote_content_sources in response."""
        response = client.get(f"/knowledge/config?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        # Verify the field exists (may be None or empty list if no sources configured)
        assert "remote_content_sources" in data

    def test_remote_content_endpoint_requires_config_id(self, client: httpx.Client):
        """Test POST /knowledge/remote-content requires config_id parameter."""
        response = client.post(
            f"/knowledge/remote-content?db_id={self.DB_ID}",
            data={
                "path": "some/file.pdf",
            },
        )
        # Should return 422 for missing required field
        assert response.status_code == 422

    def test_remote_content_endpoint_requires_path(self, client: httpx.Client):
        """Test POST /knowledge/remote-content requires path parameter."""
        response = client.post(
            f"/knowledge/remote-content?db_id={self.DB_ID}",
            data={
                "config_id": "some-config",
            },
        )
        # Should return 422 for missing required field
        assert response.status_code == 422

    def test_remote_content_endpoint_rejects_unknown_config(self, client: httpx.Client):
        """Test POST /knowledge/remote-content returns 400 for unknown config_id."""
        response = client.post(
            f"/knowledge/remote-content?db_id={self.DB_ID}",
            data={
                "config_id": "nonexistent-source",
                "path": "some/file.pdf",
            },
        )
        # Should return 400 for unknown config
        assert response.status_code == 400
        assert "Unknown content source" in response.json()["detail"]

    def test_remote_content_endpoint_accepts_optional_fields(self, client: httpx.Client):
        """Test POST /knowledge/remote-content accepts optional metadata fields."""
        # This will still fail with 400 (unknown config) but validates
        # that the endpoint accepts the optional fields without 422
        response = client.post(
            f"/knowledge/remote-content?db_id={self.DB_ID}",
            data={
                "config_id": "test-config",
                "path": "documents/report.pdf",
                "name": "My Report",
                "description": "A test report",
                "metadata": '{"key": "value"}',
            },
        )
        # Should be 400 (unknown config), not 422 (validation error)
        assert response.status_code == 400
