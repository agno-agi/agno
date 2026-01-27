"""Azure Blob Storage content loader for Knowledge.

Provides methods for loading content from Azure Blob Storage.
"""

from io import BytesIO
from typing import Any, Dict, List, Optional, cast

from agno.knowledge.content import Content, ContentStatus
from agno.knowledge.loaders.base import RemoteContentLoader
from agno.knowledge.reader import Reader
from agno.knowledge.remote_content.config import AzureBlobConfig, RemoteContentConfig
from agno.knowledge.remote_content.remote_content import AzureBlobContent
from agno.utils.log import log_debug, log_error, log_warning
from agno.utils.string import generate_id


class AzureBlobLoader(RemoteContentLoader):
    """Loader for Azure Blob Storage content."""

    # ==========================================
    # AZURE BLOB HELPERS
    # ==========================================

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
        """Load content from Azure Blob Storage (async version).

        Requires the AzureBlobConfig to contain tenant_id, client_id, client_secret,
        storage_account, and container.

        Uses the async Azure SDK to avoid blocking the event loop.

        1. Authenticate with Azure AD using client credentials
        2. List blobs in container (by prefix or single blob)
        3. Download and process each blob
        4. Insert to vector database
        """
        remote_content: AzureBlobContent = cast(AzureBlobContent, content.remote_content)
        azure_config = cast(AzureBlobConfig, config) if isinstance(config, AzureBlobConfig) else None

        if azure_config is None:
            log_error(f"Azure Blob config not found for config_id: {remote_content.config_id}")
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
                    # Skip "directory" markers (blobs ending with /)
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
                    # Try to get as a single blob first
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
                        # Blob doesn't exist - check if it's actually a folder (prefix)
                        log_debug(f"Blob {remote_content.blob_name} not found, checking if it's a folder...")
                        blobs_to_process = await list_blobs_with_prefix(remote_content.blob_name)
                        if not blobs_to_process:
                            log_error(
                                f"No blob or folder found at path: {remote_content.blob_name}. "
                                "If this is a folder, ensure files exist inside it."
                            )
                            return
                elif remote_content.prefix:
                    # List blobs with prefix
                    blobs_to_process = await list_blobs_with_prefix(remote_content.prefix)
            except Exception as e:
                log_error(f"Error listing Azure blobs: {e}")
                return

            if not blobs_to_process:
                log_warning(f"No blobs found in Azure container: {azure_config.container}")
                return

            # For single file uploads, use the original content object to preserve the ID
            # returned by the API. For folder uploads, create new content entries for each file.
            is_folder_upload = len(blobs_to_process) > 1

            # Process each blob
            for blob_info in blobs_to_process:
                blob_name = blob_info["name"]
                file_name = blob_name.split("/")[-1]

                # Build a unique virtual path for hashing
                virtual_path = f"azure://{azure_config.storage_account}/{azure_config.container}/{blob_name}"

                # Build metadata
                azure_metadata: Dict[str, str] = {
                    "source_type": "azure_blob",
                    "source_config_id": azure_config.id,
                    "source_config_name": azure_config.name,
                    "azure_storage_account": azure_config.storage_account,
                    "azure_container": azure_config.container,
                    "azure_blob_name": blob_name,
                    "azure_filename": file_name,
                }
                merged_metadata = {**azure_metadata, **(content.metadata or {})}

                # Setup Content object
                if is_folder_upload:
                    # For folder uploads, create new content entries for each file
                    relative_path = blob_name
                    if remote_content.prefix and blob_name.startswith(remote_content.prefix):
                        relative_path = blob_name[len(remote_content.prefix) :].lstrip("/")
                    content_name = f"{content.name}/{relative_path}" if content.name else blob_name

                    content_entry = Content(
                        name=content_name,
                        description=content.description,
                        path=virtual_path,
                        status=ContentStatus.PROCESSING,
                        metadata=merged_metadata,
                        file_type="azure_blob",
                    )
                    content_entry.content_hash = self._build_content_hash(content_entry)
                    content_entry.id = generate_id(content_entry.content_hash)
                else:
                    # For single file uploads, use the original content object to preserve ID
                    content_entry = content
                    content_entry.path = virtual_path
                    content_entry.status = ContentStatus.PROCESSING
                    content_entry.metadata = merged_metadata
                    content_entry.file_type = "azure_blob"
                    # Use existing id and content_hash from the original content if available
                    if not content_entry.content_hash:
                        content_entry.content_hash = self._build_content_hash(content_entry)
                    if not content_entry.id:
                        content_entry.id = generate_id(content_entry.content_hash)

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
        """Synchronous version of _load_from_azure_blob.

        Load content from Azure Blob Storage:
        1. Authenticate with Azure AD using client credentials
        2. List blobs in container (by prefix or single blob)
        3. Download and process each blob
        4. Insert to vector database
        """
        remote_content: AzureBlobContent = cast(AzureBlobContent, content.remote_content)
        azure_config = cast(AzureBlobConfig, config) if isinstance(config, AzureBlobConfig) else None

        if azure_config is None:
            log_error(f"Azure Blob config not found for config_id: {remote_content.config_id}")
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

        container_client = blob_service.get_container_client(azure_config.container)

        # Helper to list blobs with a given prefix
        def list_blobs_with_prefix(prefix: str) -> List[Dict[str, Any]]:
            """List all blobs under a given prefix (folder)."""
            results: List[Dict[str, Any]] = []
            normalized_prefix = prefix.rstrip("/") + "/" if not prefix.endswith("/") else prefix
            blobs = container_client.list_blobs(name_starts_with=normalized_prefix)
            for blob in blobs:
                # Skip "directory" markers (blobs ending with /)
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
                # Try to get as a single blob first
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
                    # Blob doesn't exist - check if it's actually a folder (prefix)
                    log_debug(f"Blob {remote_content.blob_name} not found, checking if it's a folder...")
                    blobs_to_process = list_blobs_with_prefix(remote_content.blob_name)
                    if not blobs_to_process:
                        log_error(
                            f"No blob or folder found at path: {remote_content.blob_name}. "
                            "If this is a folder, ensure files exist inside it."
                        )
                        return
            elif remote_content.prefix:
                # List blobs with prefix
                blobs_to_process = list_blobs_with_prefix(remote_content.prefix)
        except Exception as e:
            log_error(f"Error listing Azure blobs: {e}")
            return

        if not blobs_to_process:
            log_warning(f"No blobs found in Azure container: {azure_config.container}")
            return

        # For single file uploads, use the original content object to preserve the ID
        # returned by the API. For folder uploads, create new content entries for each file.
        is_folder_upload = len(blobs_to_process) > 1

        # Process each blob
        for blob_info in blobs_to_process:
            blob_name = blob_info["name"]
            file_name = blob_name.split("/")[-1]

            # Build a unique virtual path for hashing
            virtual_path = f"azure://{azure_config.storage_account}/{azure_config.container}/{blob_name}"

            # Build metadata
            azure_metadata: Dict[str, str] = {
                "source_type": "azure_blob",
                "source_config_id": azure_config.id,
                "source_config_name": azure_config.name,
                "azure_storage_account": azure_config.storage_account,
                "azure_container": azure_config.container,
                "azure_blob_name": blob_name,
                "azure_filename": file_name,
            }
            merged_metadata = {**azure_metadata, **(content.metadata or {})}

            # Setup Content object
            if is_folder_upload:
                # For folder uploads, create new content entries for each file
                relative_path = blob_name
                if remote_content.prefix and blob_name.startswith(remote_content.prefix):
                    relative_path = blob_name[len(remote_content.prefix) :].lstrip("/")
                content_name = f"{content.name}/{relative_path}" if content.name else blob_name

                content_entry = Content(
                    name=content_name,
                    description=content.description,
                    path=virtual_path,
                    status=ContentStatus.PROCESSING,
                    metadata=merged_metadata,
                    file_type="azure_blob",
                )
                content_entry.content_hash = self._build_content_hash(content_entry)
                content_entry.id = generate_id(content_entry.content_hash)
            else:
                # For single file uploads, use the original content object to preserve ID
                content_entry = content
                content_entry.path = virtual_path
                content_entry.status = ContentStatus.PROCESSING
                content_entry.metadata = merged_metadata
                content_entry.file_type = "azure_blob"
                # Use existing id and content_hash from the original content if available
                if not content_entry.content_hash:
                    content_entry.content_hash = self._build_content_hash(content_entry)
                if not content_entry.id:
                    content_entry.id = generate_id(content_entry.content_hash)

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
