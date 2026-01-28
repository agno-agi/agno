"""Azure Blob Storage content loader for Knowledge.

Provides methods for loading content from Azure Blob Storage.
"""

# mypy: disable-error-code="attr-defined"

from io import BytesIO
from typing import Any, Dict, List, Optional, cast

from agno.knowledge.content import Content, ContentStatus
from agno.knowledge.loaders.base import BaseLoader
from agno.knowledge.reader import Reader
from agno.knowledge.remote_content.config import AzureBlobConfig, RemoteContentConfig
from agno.knowledge.remote_content.remote_content import AzureBlobContent
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.utils.string import generate_id


class AzureBlobLoader(BaseLoader):
    """Loader for Azure Blob Storage content."""

    # ==========================================
    # AZURE BLOB HELPERS (shared between sync/async)
    # ==========================================

    def _validate_azure_config(
        self,
        content: Content,
        config: Optional[RemoteContentConfig],
    ) -> Optional[AzureBlobConfig]:
        """Validate and extract Azure Blob config.

        Returns:
            AzureBlobConfig if valid, None otherwise
        """
        remote_content: AzureBlobContent = cast(AzureBlobContent, content.remote_content)
        azure_config = cast(AzureBlobConfig, config) if isinstance(config, AzureBlobConfig) else None

        if azure_config is None:
            log_error(f"Azure Blob config not found for config_id: {remote_content.config_id}")
            return None

        return azure_config

    def _get_azure_blob_client(self, azure_config: AzureBlobConfig):
        """Get a sync Azure Blob Service Client using client credentials flow.

        Requires the `azure-identity` and `azure-storage-blob` packages.
        """
        try:
            from azure.identity import ClientSecretCredential  # type: ignore
            from azure.storage.blob import BlobServiceClient  # type: ignore
        except ImportError:
            raise ImportError(
                "The `azure-identity` and `azure-storage-blob` packages are not installed. "
                "Please install them via `pip install azure-identity azure-storage-blob`."
            )

        credential = ClientSecretCredential(
            tenant_id=azure_config.tenant_id,
            client_id=azure_config.client_id,
            client_secret=azure_config.client_secret,
        )

        blob_service = BlobServiceClient(
            account_url=f"https://{azure_config.storage_account}.blob.core.windows.net",
            credential=credential,
        )

        return blob_service

    def _get_azure_blob_client_async(self, azure_config: AzureBlobConfig):
        """Get an async Azure Blob Service Client using client credentials flow.

        Requires the `azure-identity` and `azure-storage-blob` packages.
        Uses the async versions from azure.storage.blob.aio and azure.identity.aio.
        """
        try:
            from azure.identity.aio import ClientSecretCredential  # type: ignore
            from azure.storage.blob.aio import BlobServiceClient  # type: ignore
        except ImportError:
            raise ImportError(
                "The `azure-identity` and `azure-storage-blob` packages are not installed. "
                "Please install them via `pip install azure-identity azure-storage-blob`."
            )

        credential = ClientSecretCredential(
            tenant_id=azure_config.tenant_id,
            client_id=azure_config.client_id,
            client_secret=azure_config.client_secret,
        )

        blob_service = BlobServiceClient(
            account_url=f"https://{azure_config.storage_account}.blob.core.windows.net",
            credential=credential,
        )

        return blob_service

    def _build_azure_metadata(
        self,
        azure_config: AzureBlobConfig,
        blob_name: str,
        file_name: str,
    ) -> Dict[str, str]:
        """Build Azure Blob-specific metadata dictionary."""
        return {
            "source_type": "azure_blob",
            "source_config_id": azure_config.id,
            "source_config_name": azure_config.name,
            "azure_storage_account": azure_config.storage_account,
            "azure_container": azure_config.container,
            "azure_blob_name": blob_name,
            "azure_filename": file_name,
        }

    def _build_azure_virtual_path(
        self,
        storage_account: str,
        container: str,
        blob_name: str,
    ) -> str:
        """Build virtual path for Azure Blob content."""
        return f"azure://{storage_account}/{container}/{blob_name}"

    def _get_azure_root_path(self, remote_content: AzureBlobContent) -> str:
        """Get the root path for computing relative paths."""
        return remote_content.prefix or ""

    # ==========================================
    # AZURE BLOB LOADERS
    # ==========================================

    async def _aload_from_azure_blob(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        config: Optional[RemoteContentConfig] = None,
    ):
        """Load content from Azure Blob Storage (async).

        Requires the AzureBlobConfig to contain tenant_id, client_id, client_secret,
        storage_account, and container.

        Uses the async Azure SDK to avoid blocking the event loop.
        """
        remote_content: AzureBlobContent = cast(AzureBlobContent, content.remote_content)
        azure_config = self._validate_azure_config(content, config)
        if azure_config is None:
            return

        # Get async blob service client
        try:
            blob_service = self._get_azure_blob_client_async(azure_config)
        except ImportError as e:
            log_error(str(e))
            return
        except Exception as e:
            log_error(f"Error creating Azure Blob client: {e}")
            return

        # Use async context manager for proper resource cleanup
        async with blob_service:
            container_client = blob_service.get_container_client(azure_config.container)

            # Helper to list blobs with a given prefix (async)
            async def list_blobs_with_prefix(prefix: str) -> List[Dict[str, Any]]:
                """List all blobs under a given prefix (folder)."""
                results: List[Dict[str, Any]] = []
                normalized_prefix = prefix.rstrip("/") + "/" if not prefix.endswith("/") else prefix
                async for blob in container_client.list_blobs(name_starts_with=normalized_prefix):
                    if not blob.name.endswith("/"):
                        results.append(
                            {
                                "name": blob.name,
                                "size": blob.size,
                                "content_type": blob.content_settings.content_type if blob.content_settings else None,
                            }
                        )
                return results

            # Identify blobs to process
            blobs_to_process: List[Dict[str, Any]] = []

            try:
                if remote_content.blob_name:
                    blob_client = container_client.get_blob_client(remote_content.blob_name)
                    try:
                        props = await blob_client.get_blob_properties()
                        blobs_to_process.append(
                            {
                                "name": remote_content.blob_name,
                                "size": props.size,
                                "content_type": props.content_settings.content_type if props.content_settings else None,
                            }
                        )
                    except Exception:
                        log_debug(f"Blob {remote_content.blob_name} not found, checking if it's a folder...")
                        blobs_to_process = await list_blobs_with_prefix(remote_content.blob_name)
                        if not blobs_to_process:
                            log_error(
                                f"No blob or folder found at path: {remote_content.blob_name}. "
                                "If this is a folder, ensure files exist inside it."
                            )
                            return
                elif remote_content.prefix:
                    blobs_to_process = await list_blobs_with_prefix(remote_content.prefix)
            except Exception as e:
                log_error(f"Error listing Azure blobs: {e}")
                return

            if not blobs_to_process:
                log_warning(f"No blobs found in Azure container: {azure_config.container}")
                return

            log_info(f"Processing {len(blobs_to_process)} file(s) from Azure Blob Storage")
            is_folder_upload = len(blobs_to_process) > 1
            root_path = self._get_azure_root_path(remote_content)

            for blob_info in blobs_to_process:
                blob_name = blob_info["name"]
                file_name = blob_name.split("/")[-1]

                # Build metadata and virtual path using helpers
                virtual_path = self._build_azure_virtual_path(
                    azure_config.storage_account, azure_config.container, blob_name
                )
                azure_metadata = self._build_azure_metadata(azure_config, blob_name, file_name)
                merged_metadata = self._merge_metadata(azure_metadata, content.metadata)

                # Compute content name using base helper
                content_name = self._compute_content_name(
                    blob_name, file_name, content.name, root_path, is_folder_upload
                )

                # Create content entry using base helper
                content_entry = self._create_content_entry(
                    content, content_name, virtual_path, merged_metadata, "azure_blob", is_folder_upload
                )

                await self._ainsert_contents_db(content_entry)

                if self._should_skip(content_entry.content_hash, skip_if_exists):
                    content_entry.status = ContentStatus.COMPLETED
                    await self._aupdate_content(content_entry)
                    continue

                # Download blob (async)
                try:
                    blob_client = container_client.get_blob_client(blob_name)
                    download_stream = await blob_client.download_blob()
                    blob_data = await download_stream.readall()
                    file_content = BytesIO(blob_data)
                except Exception as e:
                    log_error(f"Error downloading Azure blob {blob_name}: {e}")
                    content_entry.status = ContentStatus.FAILED
                    content_entry.status_message = str(e)
                    await self._aupdate_content(content_entry)
                    continue

                # Select reader and read content
                reader = self._select_reader_by_uri(file_name, content.reader)
                if reader is None:
                    log_warning(f"No reader found for file: {file_name}")
                    content_entry.status = ContentStatus.FAILED
                    content_entry.status_message = "No suitable reader found"
                    await self._aupdate_content(content_entry)
                    continue

                reader = cast(Reader, reader)
                read_documents = await reader.async_read(file_content, name=file_name)

                # Prepare and insert into vector database
                if not content_entry.id:
                    content_entry.id = generate_id(content_entry.content_hash or "")
                self._prepare_documents_for_insert(read_documents, content_entry.id)
                await self._ahandle_vector_db_insert(content_entry, read_documents, upsert)

    def _load_from_azure_blob(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        config: Optional[RemoteContentConfig] = None,
    ):
        """Load content from Azure Blob Storage (sync).

        Requires the AzureBlobConfig to contain tenant_id, client_id, client_secret,
        storage_account, and container.
        """
        remote_content: AzureBlobContent = cast(AzureBlobContent, content.remote_content)
        azure_config = self._validate_azure_config(content, config)
        if azure_config is None:
            return

        # Get blob service client
        try:
            blob_service = self._get_azure_blob_client(azure_config)
        except ImportError as e:
            log_error(str(e))
            return
        except Exception as e:
            log_error(f"Error creating Azure Blob client: {e}")
            return

        # Use context manager for proper resource cleanup
        with blob_service:
            container_client = blob_service.get_container_client(azure_config.container)

            # Helper to list blobs with a given prefix
            def list_blobs_with_prefix(prefix: str) -> List[Dict[str, Any]]:
                """List all blobs under a given prefix (folder)."""
                results: List[Dict[str, Any]] = []
                normalized_prefix = prefix.rstrip("/") + "/" if not prefix.endswith("/") else prefix
                blobs = container_client.list_blobs(name_starts_with=normalized_prefix)
                for blob in blobs:
                    if not blob.name.endswith("/"):
                        results.append(
                            {
                                "name": blob.name,
                                "size": blob.size,
                                "content_type": blob.content_settings.content_type if blob.content_settings else None,
                            }
                        )
                return results

            # Identify blobs to process
            blobs_to_process: List[Dict[str, Any]] = []

            try:
                if remote_content.blob_name:
                    blob_client = container_client.get_blob_client(remote_content.blob_name)
                    try:
                        props = blob_client.get_blob_properties()
                        blobs_to_process.append(
                            {
                                "name": remote_content.blob_name,
                                "size": props.size,
                                "content_type": props.content_settings.content_type if props.content_settings else None,
                            }
                        )
                    except Exception:
                        log_debug(f"Blob {remote_content.blob_name} not found, checking if it's a folder...")
                        blobs_to_process = list_blobs_with_prefix(remote_content.blob_name)
                        if not blobs_to_process:
                            log_error(
                                f"No blob or folder found at path: {remote_content.blob_name}. "
                                "If this is a folder, ensure files exist inside it."
                            )
                            return
                elif remote_content.prefix:
                    blobs_to_process = list_blobs_with_prefix(remote_content.prefix)
            except Exception as e:
                log_error(f"Error listing Azure blobs: {e}")
                return

            if not blobs_to_process:
                log_warning(f"No blobs found in Azure container: {azure_config.container}")
                return

            log_info(f"Processing {len(blobs_to_process)} file(s) from Azure Blob Storage")
            is_folder_upload = len(blobs_to_process) > 1
            root_path = self._get_azure_root_path(remote_content)

            for blob_info in blobs_to_process:
                blob_name = blob_info["name"]
                file_name = blob_name.split("/")[-1]

                # Build metadata and virtual path using helpers
                virtual_path = self._build_azure_virtual_path(
                    azure_config.storage_account, azure_config.container, blob_name
                )
                azure_metadata = self._build_azure_metadata(azure_config, blob_name, file_name)
                merged_metadata = self._merge_metadata(azure_metadata, content.metadata)

                # Compute content name using base helper
                content_name = self._compute_content_name(
                    blob_name, file_name, content.name, root_path, is_folder_upload
                )

                # Create content entry using base helper
                content_entry = self._create_content_entry(
                    content, content_name, virtual_path, merged_metadata, "azure_blob", is_folder_upload
                )

                self._insert_contents_db(content_entry)

                if self._should_skip(content_entry.content_hash, skip_if_exists):
                    content_entry.status = ContentStatus.COMPLETED
                    self._update_content(content_entry)
                    continue

                # Download blob
                try:
                    blob_client = container_client.get_blob_client(blob_name)
                    download_stream = blob_client.download_blob()
                    file_content = BytesIO(download_stream.readall())
                except Exception as e:
                    log_error(f"Error downloading Azure blob {blob_name}: {e}")
                    content_entry.status = ContentStatus.FAILED
                    content_entry.status_message = str(e)
                    self._update_content(content_entry)
                    continue

                # Select reader and read content
                reader = self._select_reader_by_uri(file_name, content.reader)
                if reader is None:
                    log_warning(f"No reader found for file: {file_name}")
                    content_entry.status = ContentStatus.FAILED
                    content_entry.status_message = "No suitable reader found"
                    self._update_content(content_entry)
                    continue

                reader = cast(Reader, reader)
                read_documents = reader.read(file_content, name=file_name)

                # Prepare and insert into vector database
                if not content_entry.id:
                    content_entry.id = generate_id(content_entry.content_hash or "")
                self._prepare_documents_for_insert(read_documents, content_entry.id)
                self._handle_vector_db_insert(content_entry, read_documents, upsert)
