"""Integration tests for remote content upload endpoint."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from agno.knowledge.content import Content
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.remote_content import (
    AzureBlobConfig,
    GcsConfig,
    GitHubConfig,
    S3Config,
    SharePointConfig,
)
from agno.os.routers.knowledge.knowledge import attach_routes


@pytest.fixture
def mock_knowledge_with_remote_configs():
    """Create a Knowledge instance with remote content configs."""
    content_sources = [
        S3Config(
            id="s3-docs",
            name="S3 Documents",
            bucket_name="my-docs-bucket",
            region="us-east-1",
        ),
        GcsConfig(
            id="gcs-data",
            name="GCS Data",
            bucket_name="my-data-bucket",
            project="my-project",
        ),
        GitHubConfig(
            id="github-repo",
            name="GitHub Repository",
            repo="myorg/myrepo",
            branch="main",
        ),
        SharePointConfig(
            id="sharepoint-docs",
            name="SharePoint Documents",
            tenant_id="tenant-123",
            client_id="client-456",
            client_secret="secret-789",
            hostname="contoso.sharepoint.com",
            site_id="contoso.sharepoint.com,guid1,guid2",
        ),
        AzureBlobConfig(
            id="azure-docs",
            name="Azure Documents",
            tenant_id="tenant-123",
            client_id="client-456",
            client_secret="secret-789",
            storage_account="mystorageaccount",
            container="mycontainer",
        ),
    ]

    knowledge = Knowledge(name="test_knowledge", content_sources=content_sources)

    # Mock external dependencies
    knowledge.vector_db = Mock()
    knowledge.vector_db.id = "test_vector_db_id"
    knowledge.contents_db = Mock()
    knowledge.readers = {}

    # Mock methods
    knowledge.vector_db.content_hash_exists.return_value = False
    knowledge.vector_db.async_insert = Mock()
    knowledge.vector_db.async_upsert = Mock()
    knowledge.vector_db.upsert_available.return_value = True
    knowledge.contents_db.upsert_knowledge_content = Mock()
    knowledge.contents_db.get_knowledge_contents = Mock(return_value=([], 0))

    return knowledge


@pytest.fixture
def test_app(mock_knowledge_with_remote_configs):
    """Create a FastAPI test app with knowledge routes."""
    app = FastAPI()
    router = attach_routes(APIRouter(), [mock_knowledge_with_remote_configs])
    app.include_router(router)
    return TestClient(app)


# =============================================================================
# Remote Content Endpoint Tests
# =============================================================================


def test_upload_s3_file_success(test_app):
    """Test successful S3 file upload."""
    with patch("agno.os.routers.knowledge.knowledge.process_content") as mock_process:
        response = test_app.post(
            "/knowledge/remote-content",
            data={
                "config_id": "s3-docs",
                "path": "documents/report.pdf",
                "name": "Q1 Report",
                "description": "Quarterly report",
                "metadata": '{"quarter": "Q1"}',
            },
        )

        assert response.status_code == 202
        data = response.json()
        assert "id" in data
        assert data["name"] == "Q1 Report"
        assert data["status"] == "processing"
        mock_process.assert_called_once()


def test_upload_s3_folder_success(test_app):
    """Test successful S3 folder upload (path ends with /)."""
    with patch("agno.os.routers.knowledge.knowledge.process_content") as mock_process:
        response = test_app.post(
            "/knowledge/remote-content",
            data={
                "config_id": "s3-docs",
                "path": "documents/reports/",
                "name": "All Reports",
            },
        )

        assert response.status_code == 202
        data = response.json()
        assert data["name"] == "All Reports"
        mock_process.assert_called_once()


def test_upload_github_file_success(test_app):
    """Test successful GitHub file upload."""
    with patch("agno.os.routers.knowledge.knowledge.process_content") as mock_process:
        response = test_app.post(
            "/knowledge/remote-content",
            data={
                "config_id": "github-repo",
                "path": "docs/README.md",
            },
        )

        assert response.status_code == 202
        data = response.json()
        assert data["name"] == "docs/README.md"  # Auto-generated from path
        mock_process.assert_called_once()


def test_upload_github_folder_success(test_app):
    """Test successful GitHub folder upload."""
    with patch("agno.os.routers.knowledge.knowledge.process_content") as mock_process:
        response = test_app.post(
            "/knowledge/remote-content",
            data={
                "config_id": "github-repo",
                "path": "src/api/",
                "name": "API Source Code",
            },
        )

        assert response.status_code == 202
        data = response.json()
        assert data["name"] == "API Source Code"
        mock_process.assert_called_once()


def test_upload_gcs_file_success(test_app):
    """Test successful GCS file upload."""
    with patch("agno.os.routers.knowledge.knowledge.process_content") as mock_process:
        response = test_app.post(
            "/knowledge/remote-content",
            data={
                "config_id": "gcs-data",
                "path": "data/dataset.csv",
            },
        )

        assert response.status_code == 202
        data = response.json()
        assert "id" in data
        mock_process.assert_called_once()


def test_upload_sharepoint_file_success(test_app):
    """Test successful SharePoint file upload."""
    with patch("agno.os.routers.knowledge.knowledge.process_content") as mock_process:
        response = test_app.post(
            "/knowledge/remote-content",
            data={
                "config_id": "sharepoint-docs",
                "path": "Shared Documents/report.pdf",
            },
        )

        assert response.status_code == 202
        data = response.json()
        assert "id" in data
        mock_process.assert_called_once()


def test_upload_azure_blob_file_success(test_app):
    """Test successful Azure Blob file upload."""
    with patch("agno.os.routers.knowledge.knowledge.process_content") as mock_process:
        response = test_app.post(
            "/knowledge/remote-content",
            data={
                "config_id": "azure-docs",
                "path": "documents/report.pdf",
                "name": "Azure Report",
            },
        )

        assert response.status_code == 202
        data = response.json()
        assert "id" in data
        assert data["name"] == "Azure Report"
        mock_process.assert_called_once()


def test_upload_azure_blob_folder_success(test_app):
    """Test successful Azure Blob folder upload (path ends with /)."""
    with patch("agno.os.routers.knowledge.knowledge.process_content") as mock_process:
        response = test_app.post(
            "/knowledge/remote-content",
            data={
                "config_id": "azure-docs",
                "path": "documents/reports/",
                "name": "All Azure Reports",
            },
        )

        assert response.status_code == 202
        data = response.json()
        assert data["name"] == "All Azure Reports"
        mock_process.assert_called_once()


def test_upload_unknown_config_id(test_app):
    """Test upload with unknown config_id returns 400."""
    response = test_app.post(
        "/knowledge/remote-content",
        data={
            "config_id": "unknown-source",
            "path": "file.pdf",
        },
    )

    assert response.status_code == 400
    assert "Unknown content source" in response.json()["detail"]


def test_upload_missing_config_id(test_app):
    """Test upload without config_id returns 422."""
    response = test_app.post(
        "/knowledge/remote-content",
        data={
            "path": "file.pdf",
        },
    )

    assert response.status_code == 422


def test_upload_missing_path(test_app):
    """Test upload without path returns 422."""
    response = test_app.post(
        "/knowledge/remote-content",
        data={
            "config_id": "s3-docs",
        },
    )

    assert response.status_code == 422


def test_upload_with_invalid_metadata_json(test_app):
    """Test upload with invalid JSON metadata still succeeds."""
    with patch("agno.os.routers.knowledge.knowledge.process_content"):
        response = test_app.post(
            "/knowledge/remote-content",
            data={
                "config_id": "s3-docs",
                "path": "file.pdf",
                "metadata": "not valid json",
            },
        )

        # Should still succeed - invalid JSON is wrapped in {"value": ...}
        assert response.status_code == 202


def test_upload_with_reader_id(test_app, mock_knowledge_with_remote_configs):
    """Test upload with specific reader_id."""
    # Add a mock reader
    mock_reader = Mock()
    mock_knowledge_with_remote_configs.readers = {"pdf_reader": mock_reader}

    with patch("agno.os.routers.knowledge.knowledge.process_content") as mock_process:
        response = test_app.post(
            "/knowledge/remote-content",
            data={
                "config_id": "s3-docs",
                "path": "document.pdf",
                "reader_id": "pdf_reader",
            },
        )

        assert response.status_code == 202
        # Verify reader_id was passed to process_content
        call_args = mock_process.call_args
        assert call_args[0][2] == "pdf_reader"  # Third positional arg is reader_id


def test_upload_with_chunking_params(test_app):
    """Test upload with chunking parameters."""
    with patch("agno.os.routers.knowledge.knowledge.process_content") as mock_process:
        response = test_app.post(
            "/knowledge/remote-content",
            data={
                "config_id": "github-repo",
                "path": "docs/large-file.md",
                "chunker": "recursive",
                "chunk_size": "1000",
                "chunk_overlap": "100",
            },
        )

        assert response.status_code == 202
        # Verify chunking params were passed
        call_args = mock_process.call_args
        assert call_args[0][3] == "recursive"  # chunker
        assert call_args[0][4] == 1000  # chunk_size
        assert call_args[0][5] == 100  # chunk_overlap


def test_upload_auto_generates_name_from_path(test_app):
    """Test that name is auto-generated from path when not provided."""
    with patch("agno.os.routers.knowledge.knowledge.process_content"):
        response = test_app.post(
            "/knowledge/remote-content",
            data={
                "config_id": "s3-docs",
                "path": "documents/reports/annual-2024.pdf",
            },
        )

        assert response.status_code == 202
        data = response.json()
        assert data["name"] == "documents/reports/annual-2024.pdf"


def test_folder_path_detection(test_app):
    """Test that paths ending with / are treated as folders."""
    with patch("agno.os.routers.knowledge.knowledge.process_content") as mock_process:
        # File path (no trailing slash)
        response1 = test_app.post(
            "/knowledge/remote-content",
            data={"config_id": "s3-docs", "path": "documents/file.pdf"},
        )
        assert response1.status_code == 202

        # Folder path (trailing slash)
        response2 = test_app.post(
            "/knowledge/remote-content",
            data={"config_id": "s3-docs", "path": "documents/folder/"},
        )
        assert response2.status_code == 202

        # Both should have been processed
        assert mock_process.call_count == 2


# =============================================================================
# Config Endpoint Tests
# =============================================================================


def test_config_returns_remote_sources(test_app, mock_knowledge_with_remote_configs):
    """Test that /knowledge/config returns configured remote sources."""
    # Set vector_db to None to simplify the test
    mock_knowledge_with_remote_configs.vector_db = None

    response = test_app.get("/knowledge/config")

    assert response.status_code == 200
    data = response.json()

    # Verify remote sources are included (field name is snake_case)
    assert "remote_content_sources" in data
    sources = data["remote_content_sources"]
    assert len(sources) == 5

    # Verify source structure
    source_ids = [s["id"] for s in sources]
    assert "s3-docs" in source_ids
    assert "gcs-data" in source_ids
    assert "github-repo" in source_ids
    assert "sharepoint-docs" in source_ids
    assert "azure-docs" in source_ids

    # Verify source details
    s3_source = next(s for s in sources if s["id"] == "s3-docs")
    assert s3_source["name"] == "S3 Documents"
    assert s3_source["type"] == "s3"

    github_source = next(s for s in sources if s["id"] == "github-repo")
    assert github_source["name"] == "GitHub Repository"
    assert github_source["type"] == "github"

    azure_source = next(s for s in sources if s["id"] == "azure-docs")
    assert azure_source["name"] == "Azure Documents"
    assert azure_source["type"] == "azureblob"


# =============================================================================
# Content Processing Tests
# =============================================================================


@pytest.mark.asyncio
async def test_process_content_with_remote_s3(mock_knowledge_with_remote_configs):
    """Test processing content from S3."""
    from agno.knowledge.remote_content.remote_content import S3Content
    from agno.os.routers.knowledge.knowledge import process_content

    # Create content with S3 remote source
    s3_content = S3Content(bucket_name="my-bucket", key="test.pdf", config_id="s3-docs")
    content = Content(name="Test PDF", remote_content=s3_content)

    # Mock the loading method
    with patch.object(mock_knowledge_with_remote_configs, "_aload_content", new_callable=AsyncMock) as mock_load:
        await process_content(mock_knowledge_with_remote_configs, content, None)
        mock_load.assert_called_once()


@pytest.mark.asyncio
async def test_process_content_with_remote_github(mock_knowledge_with_remote_configs):
    """Test processing content from GitHub."""
    from agno.knowledge.remote_content.remote_content import GitHubContent
    from agno.os.routers.knowledge.knowledge import process_content

    # Create content with GitHub remote source
    gh_content = GitHubContent(config_id="github-repo", file_path="docs/README.md", branch="main")
    content = Content(name="README", remote_content=gh_content)

    # Mock the loading method
    with patch.object(mock_knowledge_with_remote_configs, "_aload_content", new_callable=AsyncMock) as mock_load:
        await process_content(mock_knowledge_with_remote_configs, content, None)
        mock_load.assert_called_once()


@pytest.mark.asyncio
async def test_process_content_with_remote_azure_blob(mock_knowledge_with_remote_configs):
    """Test processing content from Azure Blob Storage."""
    from agno.knowledge.remote_content.remote_content import AzureBlobContent
    from agno.os.routers.knowledge.knowledge import process_content

    # Create content with Azure Blob remote source
    azure_content = AzureBlobContent(config_id="azure-docs", blob_name="documents/report.pdf")
    content = Content(name="Azure Report", remote_content=azure_content)

    # Mock the loading method
    with patch.object(mock_knowledge_with_remote_configs, "_aload_content", new_callable=AsyncMock) as mock_load:
        await process_content(mock_knowledge_with_remote_configs, content, None)
        mock_load.assert_called_once()
