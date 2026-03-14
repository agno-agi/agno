"""Backup storage for Knowledge.

Provides storage and retrieval of backup file contents in S3, Azure Blob, GCS,
or local filesystem. This enables features like content refresh (re-embedding
from original files) and file access by agents.
"""

import asyncio
import os
from typing import Any, Dict, List, Optional, cast

from agno.knowledge.remote_content import (
    AzureBlobConfig,
    BaseStorageConfig,
    GcsConfig,
    LocalStorageConfig,
    S3Config,
    SharePointConfig,
)
from agno.utils.log import log_error, log_info


class BackupStorage:
    """Handles storage and retrieval of backup content files.

    Supports four backends:
    - S3: For production use (via S3Config)
    - Azure Blob Storage: For Azure environments (via AzureBlobConfig)
    - Google Cloud Storage: For GCP environments (via GcsConfig)
    - Local filesystem: For development/testing (via LocalStorageConfig)
    """

    def __init__(
        self,
        storage_config: BaseStorageConfig,
        knowledge_id: Optional[str] = None,
        content_sources: Optional[List[BaseStorageConfig]] = None,
    ):
        self.storage_config = storage_config
        self.knowledge_id = knowledge_id
        self.content_sources = content_sources or []

    # ==========================================
    # STORE - Save raw content
    # ==========================================

    def store(self, content_id: str, filename: str, file_data: bytes) -> Dict[str, Any]:
        """Store backup content and return storage metadata.

        Args:
            content_id: The content ID (used as folder prefix)
            filename: Original filename
            file_data: Raw file bytes

        Returns:
            Dict with storage metadata to merge into _agno
        """
        if isinstance(self.storage_config, S3Config):
            return self._store_to_s3(content_id, filename, file_data)
        elif isinstance(self.storage_config, LocalStorageConfig):
            return self._store_to_local(content_id, filename, file_data)
        elif isinstance(self.storage_config, AzureBlobConfig):
            return self._store_to_azure_blob(content_id, filename, file_data)
        elif isinstance(self.storage_config, GcsConfig):
            return self._store_to_gcs(content_id, filename, file_data)
        else:
            raise ValueError(f"Unsupported backup storage config type: {type(self.storage_config).__name__}")

    async def astore(self, content_id: str, filename: str, file_data: bytes) -> Dict[str, Any]:
        """Async version of store.

        Uses true async I/O for Azure Blob and local filesystem.
        S3 and GCS use sync SDKs offloaded via asyncio.to_thread().
        """
        if isinstance(self.storage_config, S3Config):
            return await asyncio.to_thread(self._store_to_s3, content_id, filename, file_data)
        elif isinstance(self.storage_config, LocalStorageConfig):
            return await self._astore_to_local(content_id, filename, file_data)
        elif isinstance(self.storage_config, AzureBlobConfig):
            return await self._astore_to_azure_blob(content_id, filename, file_data)
        elif isinstance(self.storage_config, GcsConfig):
            return await asyncio.to_thread(self._store_to_gcs, content_id, filename, file_data)
        else:
            raise ValueError(f"Unsupported backup storage config type: {type(self.storage_config).__name__}")

    # ==========================================
    # FETCH - Retrieve raw content
    # ==========================================

    def fetch(self, agno_metadata: Dict[str, Any]) -> bytes:
        """Fetch backup content from storage.

        Args:
            agno_metadata: The _agno metadata dict containing storage info

        Returns:
            Raw file bytes
        """
        backup_storage_type = agno_metadata.get("backup_storage_type")
        if backup_storage_type == "s3":
            return self._fetch_from_s3(agno_metadata)
        elif backup_storage_type == "local":
            return self._fetch_from_local(agno_metadata)
        elif backup_storage_type == "azure_blob":
            return self._fetch_from_azure_blob(agno_metadata)
        elif backup_storage_type == "gcs":
            return self._fetch_from_gcs(agno_metadata)
        else:
            raise ValueError(f"Unknown backup storage type: {backup_storage_type}")

    async def afetch(self, agno_metadata: Dict[str, Any]) -> bytes:
        """Async version of fetch.

        Uses true async I/O for Azure Blob and local filesystem.
        S3 and GCS use sync SDKs offloaded via asyncio.to_thread().
        """
        backup_storage_type = agno_metadata.get("backup_storage_type")
        if backup_storage_type == "s3":
            return await asyncio.to_thread(self._fetch_from_s3, agno_metadata)
        elif backup_storage_type == "local":
            return await self._afetch_from_local(agno_metadata)
        elif backup_storage_type == "azure_blob":
            return await self._afetch_from_azure_blob(agno_metadata)
        elif backup_storage_type == "gcs":
            return await asyncio.to_thread(self._fetch_from_gcs, agno_metadata)
        else:
            raise ValueError(f"Unknown backup storage type: {backup_storage_type}")

    # ==========================================
    # FETCH FROM ORIGINAL SOURCE
    # ==========================================

    def fetch_from_source(self, agno_metadata: Dict[str, Any]) -> bytes:
        """Fetch content from the original cloud source based on _agno metadata.

        Dispatches to the appropriate cloud SDK based on source_type.
        """
        source_type = agno_metadata.get("source_type")
        if not source_type:
            raise ValueError("No source_type in metadata, cannot fetch from original source")

        if source_type == "s3":
            return self._fetch_original_s3(agno_metadata)
        elif source_type == "gcs":
            return self._fetch_original_gcs(agno_metadata)
        elif source_type == "sharepoint":
            return self._fetch_original_sharepoint(agno_metadata)
        elif source_type == "github":
            return self._fetch_original_github(agno_metadata)
        elif source_type == "azure_blob":
            return self._fetch_original_azure_blob(agno_metadata)
        else:
            raise ValueError(f"Unsupported source type for refresh: {source_type}")

    async def afetch_from_source(self, agno_metadata: Dict[str, Any]) -> bytes:
        """Async version of fetch_from_source.

        Uses true async I/O for Azure Blob, SharePoint, and GitHub.
        S3 and GCS use sync SDKs offloaded via asyncio.to_thread().
        """
        source_type = agno_metadata.get("source_type")
        if not source_type:
            raise ValueError("No source_type in metadata, cannot fetch from original source")

        if source_type == "s3":
            return await asyncio.to_thread(self._fetch_original_s3, agno_metadata)
        elif source_type == "gcs":
            return await asyncio.to_thread(self._fetch_original_gcs, agno_metadata)
        elif source_type == "sharepoint":
            return await self._afetch_original_sharepoint(agno_metadata)
        elif source_type == "github":
            return await self._afetch_original_github(agno_metadata)
        elif source_type == "azure_blob":
            return await self._afetch_original_azure_blob(agno_metadata)
        else:
            raise ValueError(f"Unsupported source type for refresh: {source_type}")

    # ==========================================
    # S3 BACKUP STORAGE
    # ==========================================
    # Note: Uses sync boto3 calls as boto3 doesn't have an async API.

    def _store_to_s3(self, content_id: str, filename: str, file_data: bytes) -> Dict[str, Any]:
        """Store backup content to S3."""
        try:
            import boto3
        except ImportError:
            raise ImportError("The `boto3` package is not installed. Please install it via `pip install boto3`.")

        config = self.storage_config
        if not isinstance(config, S3Config):
            raise ValueError("Storage config is not S3Config")

        # Build S3 key: {prefix}/{knowledge_id}/{content_id}/{filename}
        prefix = config.prefix.rstrip("/") if config.prefix else "raw"
        if self.knowledge_id:
            s3_key = f"{prefix}/{self.knowledge_id}/{content_id}/{filename}"
        else:
            s3_key = f"{prefix}/{content_id}/{filename}"

        # Build session/client
        session_kwargs: Dict[str, Any] = {}
        if config.region:
            session_kwargs["region_name"] = config.region

        client_kwargs: Dict[str, Any] = {}
        if config.aws_access_key_id and config.aws_secret_access_key:
            client_kwargs["aws_access_key_id"] = config.aws_access_key_id
            client_kwargs["aws_secret_access_key"] = config.aws_secret_access_key

        session = boto3.Session(**session_kwargs)
        s3_client = session.client("s3", **client_kwargs)

        s3_client.put_object(
            Bucket=config.bucket_name,
            Key=s3_key,
            Body=file_data,
        )

        log_info(f"Stored backup to s3://{config.bucket_name}/{s3_key}")

        return {
            "backup_storage_type": "s3",
            "backup_storage_key": s3_key,
            "backup_storage_bucket": config.bucket_name,
            "backup_storage_config_id": config.id,
        }

    def _fetch_from_s3(self, agno_metadata: Dict[str, Any]) -> bytes:
        """Fetch backup content from S3."""
        try:
            import boto3
        except ImportError:
            raise ImportError("The `boto3` package is not installed. Please install it via `pip install boto3`.")

        bucket = agno_metadata.get("backup_storage_bucket")
        key = agno_metadata.get("backup_storage_key")
        config_id = agno_metadata.get("backup_storage_config_id")

        if not bucket or not key:
            raise ValueError("Missing backup_storage_bucket or backup_storage_key in metadata")

        # Try to use the config for credentials
        config = self._resolve_config(config_id)

        session_kwargs: Dict[str, Any] = {}
        client_kwargs: Dict[str, Any] = {}
        if isinstance(config, S3Config):
            if config.region:
                session_kwargs["region_name"] = config.region
            if config.aws_access_key_id and config.aws_secret_access_key:
                client_kwargs["aws_access_key_id"] = config.aws_access_key_id
                client_kwargs["aws_secret_access_key"] = config.aws_secret_access_key

        session = boto3.Session(**session_kwargs)
        s3_client = session.client("s3", **client_kwargs)

        response = s3_client.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()

    # ==========================================
    # LOCAL BACKUP STORAGE
    # ==========================================

    def _safe_local_path(self, config: LocalStorageConfig, content_id: str, filename: str) -> tuple:
        """Build a local file path and validate it stays within base_path.

        Strips directory components from filename to prevent path traversal.

        Returns:
            Tuple of (resolved_file_path, resolved_dir_path)
        """
        from pathlib import Path

        # Strip directory components — only keep the leaf name
        safe_filename = Path(filename).name
        if not safe_filename:
            safe_filename = "content"

        if self.knowledge_id:
            dir_path = os.path.join(config.base_path, self.knowledge_id, content_id)
        else:
            dir_path = os.path.join(config.base_path, content_id)

        file_path = os.path.join(dir_path, safe_filename)

        # Resolve and verify the path is inside base_path
        resolved = Path(file_path).resolve()
        base_resolved = Path(config.base_path).resolve()
        if not resolved.is_relative_to(base_resolved):
            raise ValueError(f"Path traversal detected: {filename!r} resolves outside base_path")

        return str(resolved), str(Path(dir_path).resolve())

    def _validate_local_fetch_path(self, file_path: str) -> str:
        """Validate that a stored backup path is within the configured base_path."""
        from pathlib import Path

        config = self.storage_config
        if not isinstance(config, LocalStorageConfig):
            raise ValueError("Storage config is not LocalStorageConfig")

        resolved = Path(file_path).resolve()
        base_resolved = Path(config.base_path).resolve()
        if not resolved.is_relative_to(base_resolved):
            raise ValueError("Path traversal detected: path resolves outside base_path")

        return str(resolved)

    def _store_to_local(self, content_id: str, filename: str, file_data: bytes) -> Dict[str, Any]:
        """Store backup content to local filesystem."""
        config = self.storage_config
        if not isinstance(config, LocalStorageConfig):
            raise ValueError("Storage config is not LocalStorageConfig")

        file_path, dir_path = self._safe_local_path(config, content_id, filename)
        os.makedirs(dir_path, exist_ok=True)

        with open(file_path, "wb") as f:
            f.write(file_data)

        log_info(f"Stored backup to {file_path}")

        return {
            "backup_storage_type": "local",
            "backup_storage_path": file_path,
            "backup_storage_config_id": config.id,
        }

    async def _astore_to_local(self, content_id: str, filename: str, file_data: bytes) -> Dict[str, Any]:
        """Store backup content to local filesystem (async)."""
        import aiofiles

        config = self.storage_config
        if not isinstance(config, LocalStorageConfig):
            raise ValueError("Storage config is not LocalStorageConfig")

        file_path, dir_path = self._safe_local_path(config, content_id, filename)
        await asyncio.to_thread(os.makedirs, dir_path, exist_ok=True)

        async with aiofiles.open(file_path, "wb") as f:
            await f.write(file_data)

        log_info(f"Stored backup to {file_path}")

        return {
            "backup_storage_type": "local",
            "backup_storage_path": file_path,
            "backup_storage_config_id": config.id,
        }

    def _fetch_from_local(self, agno_metadata: Dict[str, Any]) -> bytes:
        """Fetch backup content from local filesystem."""
        file_path = agno_metadata.get("backup_storage_path")
        if not file_path:
            raise ValueError("Missing backup_storage_path in metadata")

        file_path = self._validate_local_fetch_path(file_path)

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Backup file not found: {file_path}")

        with open(file_path, "rb") as f:
            return f.read()

    async def _afetch_from_local(self, agno_metadata: Dict[str, Any]) -> bytes:
        """Fetch backup content from local filesystem (async)."""
        import aiofiles

        file_path = agno_metadata.get("backup_storage_path")
        if not file_path:
            raise ValueError("Missing backup_storage_path in metadata")

        file_path = self._validate_local_fetch_path(file_path)

        exists = await asyncio.to_thread(os.path.exists, file_path)
        if not exists:
            raise FileNotFoundError(f"Backup file not found: {file_path}")

        async with aiofiles.open(file_path, "rb") as f:
            return await f.read()

    # ==========================================
    # AZURE BLOB BACKUP STORAGE
    # ==========================================

    def _store_to_azure_blob(self, content_id: str, filename: str, file_data: bytes) -> Dict[str, Any]:
        """Store backup content to Azure Blob Storage."""
        try:
            from azure.identity import ClientSecretCredential  # type: ignore
            from azure.storage.blob import BlobServiceClient  # type: ignore
        except ImportError:
            raise ImportError(
                "The `azure-identity` and `azure-storage-blob` packages are not installed. "
                "Please install them via `pip install azure-identity azure-storage-blob`."
            )

        config = self.storage_config
        if not isinstance(config, AzureBlobConfig):
            raise ValueError("Storage config is not AzureBlobConfig")

        # Build blob name: {prefix}/{knowledge_id}/{content_id}/{filename}
        prefix = config.prefix.rstrip("/") if config.prefix else "raw"
        if self.knowledge_id:
            blob_name = f"{prefix}/{self.knowledge_id}/{content_id}/{filename}"
        else:
            blob_name = f"{prefix}/{content_id}/{filename}"

        credential = ClientSecretCredential(
            tenant_id=config.tenant_id,
            client_id=config.client_id,
            client_secret=config.client_secret,
        )

        blob_service = BlobServiceClient(
            account_url=f"https://{config.storage_account}.blob.core.windows.net",
            credential=credential,
        )

        blob_client = blob_service.get_blob_client(container=config.container, blob=blob_name)
        blob_client.upload_blob(file_data, overwrite=True)

        log_info(f"Stored backup to azure://{config.storage_account}/{config.container}/{blob_name}")

        return {
            "backup_storage_type": "azure_blob",
            "backup_storage_blob_name": blob_name,
            "backup_storage_container": config.container,
            "backup_storage_account": config.storage_account,
            "backup_storage_config_id": config.id,
        }

    async def _astore_to_azure_blob(self, content_id: str, filename: str, file_data: bytes) -> Dict[str, Any]:
        """Store backup content to Azure Blob Storage (async)."""
        try:
            from azure.identity.aio import ClientSecretCredential  # type: ignore
            from azure.storage.blob.aio import BlobServiceClient  # type: ignore
        except ImportError:
            raise ImportError(
                "The `azure-identity` and `azure-storage-blob` packages are not installed. "
                "Please install them via `pip install azure-identity azure-storage-blob`."
            )

        config = self.storage_config
        if not isinstance(config, AzureBlobConfig):
            raise ValueError("Storage config is not AzureBlobConfig")

        prefix = config.prefix.rstrip("/") if config.prefix else "raw"
        if self.knowledge_id:
            blob_name = f"{prefix}/{self.knowledge_id}/{content_id}/{filename}"
        else:
            blob_name = f"{prefix}/{content_id}/{filename}"

        credential = ClientSecretCredential(
            tenant_id=config.tenant_id,
            client_id=config.client_id,
            client_secret=config.client_secret,
        )

        blob_service = BlobServiceClient(
            account_url=f"https://{config.storage_account}.blob.core.windows.net",
            credential=credential,
        )

        async with blob_service:
            blob_client = blob_service.get_blob_client(container=config.container, blob=blob_name)
            await blob_client.upload_blob(file_data, overwrite=True)

        log_info(f"Stored backup to azure://{config.storage_account}/{config.container}/{blob_name}")

        return {
            "backup_storage_type": "azure_blob",
            "backup_storage_blob_name": blob_name,
            "backup_storage_container": config.container,
            "backup_storage_account": config.storage_account,
            "backup_storage_config_id": config.id,
        }

    def _fetch_from_azure_blob(self, agno_metadata: Dict[str, Any]) -> bytes:
        """Fetch backup content from Azure Blob Storage."""
        try:
            from azure.identity import ClientSecretCredential  # type: ignore
            from azure.storage.blob import BlobServiceClient  # type: ignore
        except ImportError:
            raise ImportError(
                "The `azure-identity` and `azure-storage-blob` packages are not installed. "
                "Please install them via `pip install azure-identity azure-storage-blob`."
            )

        container = agno_metadata.get("backup_storage_container")
        blob_name = agno_metadata.get("backup_storage_blob_name")
        storage_account = agno_metadata.get("backup_storage_account")
        config_id = agno_metadata.get("backup_storage_config_id")

        if not container or not blob_name or not storage_account:
            raise ValueError(
                "Missing backup_storage_container, backup_storage_blob_name, or backup_storage_account in metadata"
            )

        config = self._resolve_config(config_id)

        if not isinstance(config, AzureBlobConfig):
            raise ValueError(f"Config {config_id} is not an AzureBlobConfig")

        credential = ClientSecretCredential(
            tenant_id=config.tenant_id,
            client_id=config.client_id,
            client_secret=config.client_secret,
        )

        blob_service = BlobServiceClient(
            account_url=f"https://{storage_account}.blob.core.windows.net",
            credential=credential,
        )

        blob_client = blob_service.get_blob_client(container=container, blob=blob_name)
        return blob_client.download_blob().readall()

    async def _afetch_from_azure_blob(self, agno_metadata: Dict[str, Any]) -> bytes:
        """Fetch backup content from Azure Blob Storage (async)."""
        try:
            from azure.identity.aio import ClientSecretCredential  # type: ignore
            from azure.storage.blob.aio import BlobServiceClient  # type: ignore
        except ImportError:
            raise ImportError(
                "The `azure-identity` and `azure-storage-blob` packages are not installed. "
                "Please install them via `pip install azure-identity azure-storage-blob`."
            )

        container = agno_metadata.get("backup_storage_container")
        blob_name = agno_metadata.get("backup_storage_blob_name")
        storage_account = agno_metadata.get("backup_storage_account")
        config_id = agno_metadata.get("backup_storage_config_id")

        if not container or not blob_name or not storage_account:
            raise ValueError(
                "Missing backup_storage_container, backup_storage_blob_name, or backup_storage_account in metadata"
            )

        config = self._resolve_config(config_id)

        if not isinstance(config, AzureBlobConfig):
            raise ValueError(f"Config {config_id} is not an AzureBlobConfig")

        credential = ClientSecretCredential(
            tenant_id=config.tenant_id,
            client_id=config.client_id,
            client_secret=config.client_secret,
        )

        blob_service = BlobServiceClient(
            account_url=f"https://{storage_account}.blob.core.windows.net",
            credential=credential,
        )

        async with blob_service:
            blob_client = blob_service.get_blob_client(container=container, blob=blob_name)
            download_stream = await blob_client.download_blob()
            return await download_stream.readall()

    # ==========================================
    # GCS BACKUP STORAGE
    # ==========================================
    # Note: Uses sync google-cloud-storage calls as it doesn't have an async API.

    def _store_to_gcs(self, content_id: str, filename: str, file_data: bytes) -> Dict[str, Any]:
        """Store backup content to Google Cloud Storage."""
        try:
            from google.cloud import storage as gcs_storage  # type: ignore
        except ImportError:
            raise ImportError(
                "The `google-cloud-storage` package is not installed. "
                "Please install it via `pip install google-cloud-storage`."
            )

        config = self.storage_config
        if not isinstance(config, GcsConfig):
            raise ValueError("Storage config is not GcsConfig")

        # Build blob name: {prefix}/{knowledge_id}/{content_id}/{filename}
        prefix = config.prefix.rstrip("/") if config.prefix else "raw"
        if self.knowledge_id:
            blob_name = f"{prefix}/{self.knowledge_id}/{content_id}/{filename}"
        else:
            blob_name = f"{prefix}/{content_id}/{filename}"

        # Build client kwargs
        client_kwargs: Dict[str, Any] = {}
        if config.project:
            client_kwargs["project"] = config.project

        client = gcs_storage.Client(**client_kwargs)
        bucket = client.bucket(config.bucket_name)
        blob = bucket.blob(blob_name)
        blob.upload_from_string(file_data)

        log_info(f"Stored backup to gs://{config.bucket_name}/{blob_name}")

        return {
            "backup_storage_type": "gcs",
            "backup_storage_blob_name": blob_name,
            "backup_storage_bucket": config.bucket_name,
            "backup_storage_config_id": config.id,
        }

    def _fetch_from_gcs(self, agno_metadata: Dict[str, Any]) -> bytes:
        """Fetch backup content from Google Cloud Storage."""
        try:
            from google.cloud import storage as gcs_storage  # type: ignore
        except ImportError:
            raise ImportError(
                "The `google-cloud-storage` package is not installed. "
                "Please install it via `pip install google-cloud-storage`."
            )

        bucket_name = agno_metadata.get("backup_storage_bucket")
        blob_name = agno_metadata.get("backup_storage_blob_name")
        config_id = agno_metadata.get("backup_storage_config_id")

        if not bucket_name or not blob_name:
            raise ValueError("Missing backup_storage_bucket or backup_storage_blob_name in metadata")

        config = self._resolve_config(config_id)

        # Build client kwargs
        client_kwargs: Dict[str, Any] = {}
        if isinstance(config, GcsConfig) and config.project:
            client_kwargs["project"] = config.project

        client = gcs_storage.Client(**client_kwargs)
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        return blob.download_as_bytes()

    # ==========================================
    # ORIGINAL SOURCE FETCHERS (sync)
    # ==========================================

    def _fetch_original_s3(self, agno_metadata: Dict[str, Any]) -> bytes:
        """Fetch content from original S3 source."""
        try:
            import boto3
        except ImportError:
            raise ImportError("The `boto3` package is not installed. Please install it via `pip install boto3`.")

        bucket = agno_metadata.get("s3_bucket")
        key = agno_metadata.get("s3_object_name")
        config_id = agno_metadata.get("source_config_id")

        if not bucket or not key:
            raise ValueError("Missing s3_bucket or s3_object_name in metadata")

        config = self._resolve_config(config_id)

        session_kwargs: Dict[str, Any] = {}
        client_kwargs: Dict[str, Any] = {}
        if isinstance(config, S3Config):
            if config.region:
                session_kwargs["region_name"] = config.region
            if config.aws_access_key_id and config.aws_secret_access_key:
                client_kwargs["aws_access_key_id"] = config.aws_access_key_id
                client_kwargs["aws_secret_access_key"] = config.aws_secret_access_key

        session = boto3.Session(**session_kwargs)
        s3_client = session.client("s3", **client_kwargs)

        response = s3_client.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()

    def _fetch_original_gcs(self, agno_metadata: Dict[str, Any]) -> bytes:
        """Fetch content from original GCS source."""
        try:
            from google.cloud import storage as gcs_storage  # type: ignore
        except ImportError:
            raise ImportError(
                "The `google-cloud-storage` package is not installed. "
                "Please install it via `pip install google-cloud-storage`."
            )

        bucket_name = agno_metadata.get("gcs_bucket")
        blob_name = agno_metadata.get("gcs_blob_name")

        if not bucket_name or not blob_name:
            raise ValueError("Missing gcs_bucket or gcs_blob_name in metadata")

        config_id = agno_metadata.get("source_config_id")
        config = self._resolve_config(config_id)

        # Build client kwargs
        client_kwargs: Dict[str, Any] = {}
        if config and hasattr(config, "project") and config.project:
            client_kwargs["project"] = config.project

        client = gcs_storage.Client(**client_kwargs)
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        return blob.download_as_bytes()

    def _fetch_original_sharepoint(self, agno_metadata: Dict[str, Any]) -> bytes:
        """Fetch content from original SharePoint source."""
        import httpx

        config_id = agno_metadata.get("source_config_id")
        config = self._resolve_config(config_id)

        if not config or not isinstance(config, SharePointConfig):
            raise ValueError(f"SharePoint config {config_id} not found or invalid")

        sp_config = cast(SharePointConfig, config)
        access_token = sp_config._get_access_token()
        if not access_token:
            raise ValueError("Failed to acquire SharePoint access token")

        site_id = sp_config._get_site_id(access_token)
        if not site_id:
            raise ValueError("Failed to get SharePoint site ID")

        file_path = agno_metadata.get("sharepoint_file_path")
        if not file_path:
            raise ValueError("Missing sharepoint_file_path in metadata")

        headers = {"Authorization": f"Bearer {access_token}"}
        encoded_path = file_path.strip("/")
        url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root:/{encoded_path}:/content"

        response = httpx.get(url, headers=headers, follow_redirects=True)
        if response.status_code != 200:
            raise ValueError(f"SharePoint download failed: {response.status_code} - {response.text}")
        return response.content

    def _fetch_original_github(self, agno_metadata: Dict[str, Any]) -> bytes:
        """Fetch content from original GitHub source."""
        import httpx

        config_id = agno_metadata.get("source_config_id")
        config = self._resolve_config(config_id)

        repo = agno_metadata.get("github_repo")
        file_path = agno_metadata.get("github_file_path")
        branch = agno_metadata.get("github_branch", "main")

        if not repo or not file_path:
            raise ValueError("Missing github_repo or github_file_path in metadata")

        headers = {"Accept": "application/vnd.github.v3.raw"}
        if config and hasattr(config, "token") and config.token:
            headers["Authorization"] = f"token {config.token}"

        url = f"https://api.github.com/repos/{repo}/contents/{file_path}?ref={branch}"
        response = httpx.get(url, headers=headers)
        if response.status_code != 200:
            raise ValueError(f"GitHub download failed: {response.status_code} - {response.text}")
        return response.content

    def _fetch_original_azure_blob(self, agno_metadata: Dict[str, Any]) -> bytes:
        """Fetch content from original Azure Blob source."""
        try:
            from azure.identity import ClientSecretCredential  # type: ignore
            from azure.storage.blob import BlobServiceClient  # type: ignore
        except ImportError:
            raise ImportError(
                "The `azure-identity` and `azure-storage-blob` packages are not installed. "
                "Please install them via `pip install azure-identity azure-storage-blob`."
            )

        config_id = agno_metadata.get("source_config_id")
        config = self._resolve_config(config_id)

        storage_account = agno_metadata.get("azure_storage_account")
        container = agno_metadata.get("azure_container")
        blob_name = agno_metadata.get("azure_blob_name")

        if not storage_account or not container or not blob_name:
            raise ValueError("Missing azure_storage_account, azure_container, or azure_blob_name in metadata")

        if not config or not isinstance(config, AzureBlobConfig):
            raise ValueError(f"Azure Blob config {config_id} not found or invalid")

        azure_config = cast(AzureBlobConfig, config)
        credential = ClientSecretCredential(
            tenant_id=azure_config.tenant_id,
            client_id=azure_config.client_id,
            client_secret=azure_config.client_secret,
        )

        blob_service = BlobServiceClient(
            account_url=f"https://{storage_account}.blob.core.windows.net",
            credential=credential,
        )

        blob_client = blob_service.get_blob_client(container=container, blob=blob_name)
        return blob_client.download_blob().readall()

    # ==========================================
    # ORIGINAL SOURCE FETCHERS (async)
    # ==========================================

    async def _afetch_original_sharepoint(self, agno_metadata: Dict[str, Any]) -> bytes:
        """Fetch content from original SharePoint source (async)."""
        import httpx

        config_id = agno_metadata.get("source_config_id")
        config = self._resolve_config(config_id)

        if not config or not isinstance(config, SharePointConfig):
            raise ValueError(f"SharePoint config {config_id} not found or invalid")

        sp_config = cast(SharePointConfig, config)
        # MSAL token acquisition is sync-only (local computation + token cache)
        access_token = sp_config._get_access_token()
        if not access_token:
            raise ValueError("Failed to acquire SharePoint access token")

        # Get site ID using async HTTP
        if sp_config.site_id:
            site_id: Optional[str] = sp_config.site_id
        else:
            if sp_config.site_path:
                site_url = f"https://graph.microsoft.com/v1.0/sites/{sp_config.hostname}:/{sp_config.site_path}"
            else:
                site_url = f"https://graph.microsoft.com/v1.0/sites/{sp_config.hostname}"
            async with httpx.AsyncClient() as client:
                site_response = await client.get(site_url, headers={"Authorization": f"Bearer {access_token}"})
                site_id = site_response.json().get("id") if site_response.status_code == 200 else None

        if not site_id:
            raise ValueError("Failed to get SharePoint site ID")

        file_path = agno_metadata.get("sharepoint_file_path")
        if not file_path:
            raise ValueError("Missing sharepoint_file_path in metadata")

        headers = {"Authorization": f"Bearer {access_token}"}
        encoded_path = file_path.strip("/")
        url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root:/{encoded_path}:/content"

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, follow_redirects=True)
            if response.status_code != 200:
                raise ValueError(f"SharePoint download failed: {response.status_code} - {response.text}")
            return response.content

    async def _afetch_original_github(self, agno_metadata: Dict[str, Any]) -> bytes:
        """Fetch content from original GitHub source (async)."""
        import httpx

        config_id = agno_metadata.get("source_config_id")
        config = self._resolve_config(config_id)

        repo = agno_metadata.get("github_repo")
        file_path = agno_metadata.get("github_file_path")
        branch = agno_metadata.get("github_branch", "main")

        if not repo or not file_path:
            raise ValueError("Missing github_repo or github_file_path in metadata")

        headers: Dict[str, str] = {"Accept": "application/vnd.github.v3.raw"}
        if config and hasattr(config, "token") and config.token:
            headers["Authorization"] = f"token {config.token}"

        url = f"https://api.github.com/repos/{repo}/contents/{file_path}?ref={branch}"
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            if response.status_code != 200:
                raise ValueError(f"GitHub download failed: {response.status_code} - {response.text}")
            return response.content

    async def _afetch_original_azure_blob(self, agno_metadata: Dict[str, Any]) -> bytes:
        """Fetch content from original Azure Blob source (async)."""
        try:
            from azure.identity.aio import ClientSecretCredential  # type: ignore
            from azure.storage.blob.aio import BlobServiceClient  # type: ignore
        except ImportError:
            raise ImportError(
                "The `azure-identity` and `azure-storage-blob` packages are not installed. "
                "Please install them via `pip install azure-identity azure-storage-blob`."
            )

        config_id = agno_metadata.get("source_config_id")
        config = self._resolve_config(config_id)

        storage_account = agno_metadata.get("azure_storage_account")
        container = agno_metadata.get("azure_container")
        blob_name = agno_metadata.get("azure_blob_name")

        if not storage_account or not container or not blob_name:
            raise ValueError("Missing azure_storage_account, azure_container, or azure_blob_name in metadata")

        if not config or not isinstance(config, AzureBlobConfig):
            raise ValueError(f"Azure Blob config {config_id} not found or invalid")

        azure_config = cast(AzureBlobConfig, config)
        credential = ClientSecretCredential(
            tenant_id=azure_config.tenant_id,
            client_id=azure_config.client_id,
            client_secret=azure_config.client_secret,
        )

        blob_service = BlobServiceClient(
            account_url=f"https://{storage_account}.blob.core.windows.net",
            credential=credential,
        )

        async with blob_service:
            blob_client = blob_service.get_blob_client(container=container, blob=blob_name)
            download_stream = await blob_client.download_blob()
            return await download_stream.readall()

    # ==========================================
    # HELPERS
    # ==========================================

    def _resolve_config(self, config_id: Optional[str]) -> Optional[BaseStorageConfig]:
        """Resolve a config by ID from content_sources or fall back to storage_config."""
        if not config_id:
            return self.storage_config
        # Check content_sources first
        for source in self.content_sources:
            if source.id == config_id:
                return source
        # Fall back to storage_config if its ID matches
        if self.storage_config.id == config_id:
            return self.storage_config
        log_error(f"Config {config_id} not found in content_sources")
        return None
