"""Unit tests for remote content configuration classes."""

import pytest
from pydantic import ValidationError

from agno.knowledge.remote_content import (
    AzureBlobConfig,
    BaseStorageConfig,
    GcsConfig,
    GitHubConfig,
    S3Config,
    SharePointConfig,
)

# =============================================================================
# Base BaseStorageConfig Tests
# =============================================================================


def test_base_config_creation():
    """Test creating a base config with required fields."""
    config = BaseStorageConfig(id="test-id", name="Test Config")
    assert config.id == "test-id"
    assert config.name == "Test Config"
    assert config.metadata is None


def test_base_config_with_metadata():
    """Test creating a base config with metadata."""
    metadata = {"key": "value", "nested": {"foo": "bar"}}
    config = BaseStorageConfig(id="test-id", name="Test Config", metadata=metadata)
    assert config.metadata == metadata


def test_base_config_missing_required_fields():
    """Test that missing required fields raise ValidationError."""
    with pytest.raises(ValidationError):
        BaseStorageConfig(id="test-id")  # missing name

    with pytest.raises(ValidationError):
        BaseStorageConfig(name="Test")  # missing id


def test_base_config_allows_extra_fields():
    """Test that extra fields are allowed (Config.extra = 'allow')."""
    config = BaseStorageConfig(id="test-id", name="Test", custom_field="custom_value")
    assert config.custom_field == "custom_value"


# =============================================================================
# S3Config Tests
# =============================================================================


def test_s3_config_creation():
    """Test creating an S3 config with required fields."""
    config = S3Config(id="s3-source", name="My S3 Bucket", bucket_name="my-bucket")
    assert config.id == "s3-source"
    assert config.name == "My S3 Bucket"
    assert config.bucket_name == "my-bucket"
    assert config.region is None
    assert config.aws_access_key_id is None
    assert config.aws_secret_access_key is None
    assert config.prefix is None


def test_s3_config_with_credentials():
    """Test creating an S3 config with AWS credentials."""
    config = S3Config(
        id="s3-source",
        name="My S3 Bucket",
        bucket_name="my-bucket",
        region="us-east-1",
        aws_access_key_id="AKIAIOSFODNN7EXAMPLE",
        aws_secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        prefix="documents/",
    )
    assert config.region == "us-east-1"
    assert config.aws_access_key_id == "AKIAIOSFODNN7EXAMPLE"
    assert config.aws_secret_access_key == "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    assert config.prefix == "documents/"


def test_s3_config_file_method():
    """Test the file() method creates correct S3Content."""
    config = S3Config(id="s3-source", name="My S3 Bucket", bucket_name="my-bucket")
    content = config.file("path/to/document.pdf")

    assert content.bucket_name == "my-bucket"
    assert content.key == "path/to/document.pdf"
    assert content.config_id == "s3-source"


def test_s3_config_folder_method():
    """Test the folder() method creates correct S3Content."""
    config = S3Config(id="s3-source", name="My S3 Bucket", bucket_name="my-bucket")
    content = config.folder("documents/2024/")

    assert content.bucket_name == "my-bucket"
    assert content.prefix == "documents/2024/"
    assert content.config_id == "s3-source"


def test_s3_config_missing_bucket_name():
    """Test that missing bucket_name raises ValidationError."""
    with pytest.raises(ValidationError):
        S3Config(id="s3-source", name="My S3 Bucket")


def test_s3_config_with_metadata():
    """Test S3Config with metadata."""
    metadata = {"environment": "production", "team": "data"}
    config = S3Config(id="s3", name="S3", bucket_name="bucket", metadata=metadata)
    assert config.metadata == metadata


# =============================================================================
# GcsConfig Tests
# =============================================================================


def test_gcs_config_creation():
    """Test creating a GCS config with required fields."""
    config = GcsConfig(id="gcs-source", name="My GCS Bucket", bucket_name="my-bucket")
    assert config.id == "gcs-source"
    assert config.name == "My GCS Bucket"
    assert config.bucket_name == "my-bucket"
    assert config.project is None
    assert config.credentials_path is None
    assert config.prefix is None


def test_gcs_config_with_all_fields():
    """Test creating a GCS config with all fields."""
    config = GcsConfig(
        id="gcs-source",
        name="My GCS Bucket",
        bucket_name="my-bucket",
        project="my-project",
        credentials_path="/path/to/credentials.json",
        prefix="data/",
    )
    assert config.project == "my-project"
    assert config.credentials_path == "/path/to/credentials.json"
    assert config.prefix == "data/"


def test_gcs_config_file_method():
    """Test the file() method creates correct GCSContent."""
    config = GcsConfig(id="gcs-source", name="My GCS Bucket", bucket_name="my-bucket")
    content = config.file("path/to/document.pdf")

    assert content.bucket_name == "my-bucket"
    assert content.blob_name == "path/to/document.pdf"
    assert content.config_id == "gcs-source"


def test_gcs_config_folder_method():
    """Test the folder() method creates correct GCSContent."""
    config = GcsConfig(id="gcs-source", name="My GCS Bucket", bucket_name="my-bucket")
    content = config.folder("documents/2024/")

    assert content.bucket_name == "my-bucket"
    assert content.prefix == "documents/2024/"
    assert content.config_id == "gcs-source"


def test_gcs_config_with_metadata():
    """Test GcsConfig with metadata."""
    metadata = {"project_type": "analytics"}
    config = GcsConfig(id="gcs", name="GCS", bucket_name="bucket", metadata=metadata)
    assert config.metadata == metadata


# =============================================================================
# SharePointConfig Tests
# =============================================================================


def test_sharepoint_config_creation():
    """Test creating a SharePoint config with required fields."""
    config = SharePointConfig(
        id="sp-source",
        name="My SharePoint",
        tenant_id="tenant-123",
        client_id="client-456",
        client_secret="secret-789",
        hostname="contoso.sharepoint.com",
    )
    assert config.id == "sp-source"
    assert config.name == "My SharePoint"
    assert config.tenant_id == "tenant-123"
    assert config.client_id == "client-456"
    assert config.client_secret == "secret-789"
    assert config.hostname == "contoso.sharepoint.com"
    assert config.site_path is None
    assert config.site_id is None
    assert config.folder_path is None


def test_sharepoint_config_with_site_id():
    """Test creating a SharePoint config with site_id."""
    config = SharePointConfig(
        id="sp-source",
        name="My SharePoint",
        tenant_id="tenant-123",
        client_id="client-456",
        client_secret="secret-789",
        hostname="contoso.sharepoint.com",
        site_id="contoso.sharepoint.com,guid1,guid2",
    )
    assert config.site_id == "contoso.sharepoint.com,guid1,guid2"


def test_sharepoint_config_file_method():
    """Test the file() method creates correct SharePointContent."""
    config = SharePointConfig(
        id="sp-source",
        name="My SharePoint",
        tenant_id="tenant-123",
        client_id="client-456",
        client_secret="secret-789",
        hostname="contoso.sharepoint.com",
        site_path="/sites/documents",
    )
    content = config.file("Shared Documents/report.pdf")

    assert content.config_id == "sp-source"
    assert content.file_path == "Shared Documents/report.pdf"
    assert content.site_path == "/sites/documents"


def test_sharepoint_config_file_method_with_site_override():
    """Test the file() method with site_path override."""
    config = SharePointConfig(
        id="sp-source",
        name="My SharePoint",
        tenant_id="tenant-123",
        client_id="client-456",
        client_secret="secret-789",
        hostname="contoso.sharepoint.com",
        site_path="/sites/documents",
    )
    content = config.file("report.pdf", site_path="/sites/other")

    assert content.site_path == "/sites/other"


def test_sharepoint_config_folder_method():
    """Test the folder() method creates correct SharePointContent."""
    config = SharePointConfig(
        id="sp-source",
        name="My SharePoint",
        tenant_id="tenant-123",
        client_id="client-456",
        client_secret="secret-789",
        hostname="contoso.sharepoint.com",
    )
    content = config.folder("Shared Documents/Reports")

    assert content.config_id == "sp-source"
    assert content.folder_path == "Shared Documents/Reports"


def test_sharepoint_config_missing_required_fields():
    """Test that missing required fields raise ValidationError."""
    with pytest.raises(ValidationError):
        SharePointConfig(
            id="sp-source",
            name="My SharePoint",
            # Missing tenant_id, client_id, client_secret, hostname
        )


def test_sharepoint_config_with_metadata():
    """Test SharePointConfig with metadata."""
    metadata = {"department": "hr"}
    config = SharePointConfig(
        id="sp",
        name="SP",
        tenant_id="t",
        client_id="c",
        client_secret="s",
        hostname="h.sharepoint.com",
        metadata=metadata,
    )
    assert config.metadata == metadata


# =============================================================================
# GitHubConfig Tests
# =============================================================================


def test_github_config_creation():
    """Test creating a GitHub config with required fields."""
    config = GitHubConfig(id="gh-source", name="My Repo", repo="owner/repo")
    assert config.id == "gh-source"
    assert config.name == "My Repo"
    assert config.repo == "owner/repo"
    assert config.token is None
    assert config.branch is None
    assert config.path is None


def test_github_config_with_all_fields():
    """Test creating a GitHub config with all fields."""
    config = GitHubConfig(
        id="gh-source",
        name="My Repo",
        repo="owner/repo",
        token="ghp_xxxxxxxxxxxx",
        branch="main",
        path="docs/",
    )
    assert config.token == "ghp_xxxxxxxxxxxx"
    assert config.branch == "main"
    assert config.path == "docs/"


def test_github_config_file_method():
    """Test the file() method creates correct GitHubContent."""
    config = GitHubConfig(id="gh-source", name="My Repo", repo="owner/repo", branch="main")
    content = config.file("docs/README.md")

    assert content.config_id == "gh-source"
    assert content.file_path == "docs/README.md"
    assert content.branch == "main"


def test_github_config_file_method_with_branch_override():
    """Test the file() method with branch override."""
    config = GitHubConfig(id="gh-source", name="My Repo", repo="owner/repo", branch="main")
    content = config.file("docs/README.md", branch="develop")

    assert content.branch == "develop"


def test_github_config_folder_method():
    """Test the folder() method creates correct GitHubContent."""
    config = GitHubConfig(id="gh-source", name="My Repo", repo="owner/repo", branch="main")
    content = config.folder("src/api")

    assert content.config_id == "gh-source"
    assert content.folder_path == "src/api"
    assert content.branch == "main"


def test_github_config_folder_method_with_branch_override():
    """Test the folder() method with branch override."""
    config = GitHubConfig(id="gh-source", name="My Repo", repo="owner/repo", branch="main")
    content = config.folder("src/api", branch="feature-branch")

    assert content.branch == "feature-branch"


def test_github_config_missing_repo():
    """Test that missing repo raises ValidationError."""
    with pytest.raises(ValidationError):
        GitHubConfig(id="gh-source", name="My Repo")


def test_github_config_with_metadata():
    """Test GitHubConfig with metadata."""
    metadata = {"visibility": "private", "language": "python"}
    config = GitHubConfig(id="gh", name="GH", repo="owner/repo", metadata=metadata)
    assert config.metadata == metadata


# =============================================================================
# AzureBlobConfig Tests
# =============================================================================


def test_azure_blob_config_creation():
    """Test creating an Azure Blob config with required fields."""
    config = AzureBlobConfig(
        id="azure-source",
        name="My Azure Storage",
        tenant_id="tenant-123",
        client_id="client-456",
        client_secret="secret-789",
        storage_account="mystorageaccount",
        container="mycontainer",
    )
    assert config.id == "azure-source"
    assert config.name == "My Azure Storage"
    assert config.tenant_id == "tenant-123"
    assert config.client_id == "client-456"
    assert config.client_secret == "secret-789"
    assert config.storage_account == "mystorageaccount"
    assert config.container == "mycontainer"
    assert config.prefix is None


def test_azure_blob_config_with_prefix():
    """Test creating an Azure Blob config with a prefix."""
    config = AzureBlobConfig(
        id="azure-source",
        name="My Azure Storage",
        tenant_id="tenant-123",
        client_id="client-456",
        client_secret="secret-789",
        storage_account="mystorageaccount",
        container="mycontainer",
        prefix="documents/",
    )
    assert config.prefix == "documents/"


def test_azure_blob_config_file_method():
    """Test the file() method creates correct AzureBlobContent."""
    config = AzureBlobConfig(
        id="azure-source",
        name="My Azure Storage",
        tenant_id="tenant-123",
        client_id="client-456",
        client_secret="secret-789",
        storage_account="mystorageaccount",
        container="mycontainer",
    )
    content = config.file("path/to/document.pdf")

    assert content.config_id == "azure-source"
    assert content.blob_name == "path/to/document.pdf"
    assert content.prefix is None


def test_azure_blob_config_folder_method():
    """Test the folder() method creates correct AzureBlobContent."""
    config = AzureBlobConfig(
        id="azure-source",
        name="My Azure Storage",
        tenant_id="tenant-123",
        client_id="client-456",
        client_secret="secret-789",
        storage_account="mystorageaccount",
        container="mycontainer",
    )
    content = config.folder("documents/2024/")

    assert content.config_id == "azure-source"
    assert content.prefix == "documents/2024/"
    assert content.blob_name is None


def test_azure_blob_config_missing_required_fields():
    """Test that missing required fields raise ValidationError."""
    with pytest.raises(ValidationError):
        AzureBlobConfig(
            id="azure-source",
            name="My Azure Storage",
            # Missing tenant_id, client_id, client_secret, storage_account, container
        )


def test_azure_blob_config_missing_storage_account():
    """Test that missing storage_account raises ValidationError."""
    with pytest.raises(ValidationError):
        AzureBlobConfig(
            id="azure-source",
            name="My Azure Storage",
            tenant_id="tenant-123",
            client_id="client-456",
            client_secret="secret-789",
            container="mycontainer",
            # Missing storage_account
        )


def test_azure_blob_config_missing_container():
    """Test that missing container raises ValidationError."""
    with pytest.raises(ValidationError):
        AzureBlobConfig(
            id="azure-source",
            name="My Azure Storage",
            tenant_id="tenant-123",
            client_id="client-456",
            client_secret="secret-789",
            storage_account="mystorageaccount",
            # Missing container
        )


def test_azure_blob_config_with_metadata():
    """Test AzureBlobConfig with metadata."""
    metadata = {"environment": "production", "department": "finance"}
    config = AzureBlobConfig(
        id="azure",
        name="Azure",
        tenant_id="t",
        client_id="c",
        client_secret="s",
        storage_account="account",
        container="container",
        metadata=metadata,
    )
    assert config.metadata == metadata
