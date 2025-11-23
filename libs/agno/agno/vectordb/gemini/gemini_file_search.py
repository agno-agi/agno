import asyncio
import tempfile
import time
from typing import Any, Dict, List, Optional

try:
    from google import genai
    from google.genai import types
    from google.genai.errors import ClientError
    from google.genai.types import (
        CreateFileSearchStoreConfigDict,
        CustomMetadata,
        DeleteDocumentConfigDict,
        DeleteFileSearchStoreConfigDict,
        StringList,
        UploadToFileSearchStoreConfigDict,
    )
except ImportError:
    raise ImportError("`google-genai` not installed. Please install using `pip install google-genai`")

from agno.knowledge.document import Document
from agno.utils.log import log_debug, log_info, logger
from agno.vectordb.base import VectorDb
from agno.vectordb.search import SearchType


class GeminiFileSearch(VectorDb):
    """
    GeminiFileSearch class for managing vector operations with Google's Gemini File Search Store API.
    """

    def __init__(
        self,
        file_search_store_name: str,
        model_name: str = "gemini-2.5-flash-lite",
        api_key: Optional[str] = None,
        gemini_client: Optional[genai.Client] = None,
        **kwargs,
    ):
        """
        Initialize the GeminiFileSearch instance.

        Args:
            file_search_store_name (str): Display name for the File Search store.
            model_name (str): Name of the Gemini model to use for queries. Defaults to "gemini-2.5-flash-lite".
            api_key (Optional[str]): Gemini API key for Gemini client.
            gemini_client (Optional[genai.Client]): Gemini client instance. If not provided, creates one with api_key.

        Note:
            Gemini FileSearchStore and Documents have name and displayName attributes. It does not have an id attribute.
            name: A system-generated unique identifier for the resource.
            displayName: A user-defined name for the resource.
        """
        if not file_search_store_name:
            raise ValueError("File search name must be provided.")

        super().__init__(name=file_search_store_name, **kwargs)

        # Initialize client with api_key if provided
        if gemini_client is not None:
            self.client = gemini_client
        elif api_key is not None:
            self.client = genai.Client(api_key=api_key)
        else:
            self.client = genai.Client()

        self.api_key = api_key
        self.model_name = model_name
        self.file_search_store_name = file_search_store_name
        self.file_search_store: Optional[Any] = None  # Store FileSearchStore reference
        log_debug(
            f"Initialized GeminiFileSearch with store '{self.file_search_store_name}' and model '{self.model_name}'"
        )

    def create(self) -> None:
        """Initialize or get the File Search store."""
        try:
            # Try to get existing File Search store by display name
            stores = self.client.file_search_stores.list()
            for store in stores:
                if store.display_name == self.file_search_store_name:
                    self.file_search_store = store
                    log_debug(
                        f"Found existing File Search store '{self.file_search_store_name}' with name '{store.name}'"
                    )
                    return

            # Create new File Search store if it doesn't exist
            self.file_search_store = self.client.file_search_stores.create(
                config=CreateFileSearchStoreConfigDict(display_name=self.file_search_store_name)
            )
            log_debug(
                f"Created new File Search store '{self.file_search_store_name}' with name '{self.file_search_store.name}'"
            )
        except Exception as e:
            logger.error(f"Error initializing File Search store: {e}")
            raise

    async def async_create(self) -> None:
        """Async version of create method."""
        await asyncio.to_thread(self.create)

    def exists(self) -> bool:
        """Check if the File Search store exists."""
        try:
            stores = self.client.file_search_stores.list()
            for store in stores:
                if store.display_name == self.file_search_store_name:
                    return True
            return False
        except Exception as e:
            logger.error(f"Error checking if File Search store exists: {e}")
            return False

    async def async_exists(self) -> bool:
        """Async version of exists method."""
        return await asyncio.to_thread(self.exists)

    def name_exists(self, name: str) -> bool:
        """Check if a document with the given name exists."""
        if not self.file_search_store:
            return False

        display_name = name
        try:
            name = self.get_document_name_by_display_name(display_name)
            return self.id_exists(name)
        except ClientError as e:
            logger.error(f"Error checking if document name exists: {e}")
            raise

    async def async_name_exists(self, name: str) -> bool:
        """Async version of name_exists method."""
        return await asyncio.to_thread(self.name_exists, name)

    def id_exists(self, id: str) -> bool:
        """Check if a document with the given ID exists in the File Search store."""
        if not self.file_search_store:
            return False

        try:
            document = self.client.file_search_stores.documents.get(name=id)
            return True
        except ClientError as e:
            if e.code == 404:
                return False
            else:
                logger.error(f"Error checking if document name exists: {e}")
                raise

    def content_hash_exists(self, content_hash: str) -> bool:
        """Check if a document with the given content hash exists."""
        # Not supported by Gemini File Search
        return False

    def insert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents by uploading to File Search store."""
        if not documents:
            return

        if not self.file_search_store:
            raise ValueError("File Search store not initialized.")

        try:
            for document in documents:
                # Create temporary file with content
                with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as temp_file:
                    temp_file.write(document.content + "\n\n")
                    temp_file_path = temp_file.name

                # Upload and import file directly to File Search store
                display_name = document.name if document.name else content_hash

                # Prepare custom metadata if available
                custom_metadata = []
                document_meta_data = document.meta_data if document.meta_data else {}
                if document_meta_data:
                    for key, value in document_meta_data.items():
                        if isinstance(value, (int, float)):
                            custom_metadata.append(CustomMetadata(key=key, numeric_value=value))
                        elif isinstance(value, StringList):
                            custom_metadata.append(CustomMetadata(key=key, string_list_value=value))
                        else:
                            custom_metadata.append(CustomMetadata(key=key, string_value=str(value)))

                # Upload directly to file search store
                operation = self.client.file_search_stores.upload_to_file_search_store(
                    file=temp_file_path,
                    file_search_store_name=self.file_search_store.name,
                    config=UploadToFileSearchStoreConfigDict(
                        display_name=display_name, custom_metadata=custom_metadata
                    ),
                )

                # Wait for operation to complete
                while not operation.done:
                    time.sleep(5)
                    operation = self.client.operations.get(operation)

                log_debug(f"Uploaded and imported file to File Search store with display name: {display_name}")

                # Clean up temp file
                import os

                os.unlink(temp_file_path)

        except Exception as e:
            logger.error(f"Error inserting documents: {e}")
            raise

    async def async_insert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """Async version of insert method."""
        await asyncio.to_thread(self.insert, content_hash, documents, filters)

    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """Search for documents using the File Search tool."""
        if not self.file_search_store:
            raise ValueError("File Search store not initialized.")

        try:
            # Prepare file search tool configuration
            file_search_config = types.Tool(
                file_search=types.FileSearch(file_search_store_names=[self.file_search_store.name])
            )

            # Add metadata filter if provided
            if filters:
                metadata_filter = " AND ".join([f'{k}="{v}"' for k, v in filters.items()])
                file_search_config = types.Tool(
                    file_search=types.FileSearch(
                        file_search_store_names=[self.file_search_store.name], metadata_filter=metadata_filter
                    )
                )

            # Use generate_content with file search tool
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=query,
                config=types.GenerateContentConfig(
                    tools=[file_search_config],
                    system_instruction="You are a helpful assistant that answers questions based on the provided documents. Provide specific, detailed information from the documents.",
                    temperature=0.1,
                ),
            )

            # Return the response as a document with grounding metadata
            if response.text:
                result_doc = Document(content=response.text, name="search_result")
                # Include citation/grounding metadata if available
                if hasattr(response, "candidates") and response.candidates:
                    if hasattr(response.candidates[0], "grounding_metadata"):
                        result_doc.meta_data = {"grounding_metadata": str(response.candidates[0].grounding_metadata)}
                return [result_doc]
            return []
        except Exception as e:
            logger.error(f"Error in search: {e}")
            return []

    async def async_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """Async version of search method."""
        return await asyncio.to_thread(self.search, query, limit, filters)

    def drop(self) -> None:
        """Delete the File Search store and all its documents."""
        try:
            if not self.file_search_store:
                raise ValueError("File Search store not initialized.")

            # Delete the File Search store (force delete to remove all documents)
            self.client.file_search_stores.delete(
                name=self.file_search_store.name, config=DeleteFileSearchStoreConfigDict(force=True)
            )
            log_debug(f"Deleted File Search store '{self.file_search_store_name}'")
            self.file_search_store = None
        except Exception as e:
            logger.error(f"Error dropping File Search store: {e}")
            raise

    async def async_drop(self) -> None:
        """Async version of drop method."""
        await asyncio.to_thread(self.drop)

    def get_supported_search_types(self) -> List[str]:
        """Get list of supported search types."""
        return [SearchType.keyword.value]

    def doc_exists(self, document: Document) -> bool:
        """Not directly supported. Checks if a document with similar content might exist."""
        log_info("doc_exists is not efficiently supported by GeminiFileSearch. It performs a search.")
        results = self.search(query=document.content, limit=1)
        return len(results) > 0

    async def async_doc_exists(self, document: Document) -> bool:
        return await asyncio.to_thread(self.doc_exists, document)

    def delete_by_id(self, id: str) -> bool:
        """Delete a document from the File Search store by its ID or display name."""
        try:
            if not self.file_search_store:
                raise ValueError("File Search store not initialized.")

            self.client.file_search_stores.documents.delete(
                name=id,
                config=DeleteDocumentConfigDict(force=True)
            )
            return True
        except Exception as e:
            logger.error(f"Error deleting document by ID: {e}")
            return False

    def delete_by_name(self, name: str) -> bool:
        """Alias for delete_by_id."""
        id = self.get_document_name_by_display_name(name)
        return self.delete_by_id(id)

    def upsert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Upsert documents. Deletes documents with the same name and re-inserts."""
        if not documents:
            return
        for document in documents:
            doc_name = document.name
            if doc_name:
                self.delete_by_name(doc_name)
            self.insert(content_hash, documents, filters)

    async def async_upsert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        await asyncio.to_thread(self.upsert, content_hash, documents, filters)

    def delete(self) -> bool:
        """Deletes all documents in the store. Recreates the store."""
        self.drop()
        self.create()
        return True

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        """Delete documents by metadata. Not supported by Gemini File Search."""
        log_info("delete_by_metadata is not supported by GeminiFileSearch.")
        return False

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        """Update document metadata. Not supported by Gemini File Search."""
        log_info("update_metadata is not supported by GeminiFileSearch.")
        raise NotImplementedError("update_metadata is not supported by GeminiFileSearch")

    def delete_by_content_id(self, content_id: str) -> bool:
        """Delete a document by content ID. Uses delete_by_id."""
        return self.delete_by_id(content_id)

    def get_document_name_by_display_name(self, display_name: str) -> Optional[str]:
        """Get the document name (ID) by its display name."""
        if not self.file_search_store:
            raise ValueError("File Search store not initialized.")

        try:
            documents = self.client.file_search_stores.documents.list(parent=self.file_search_store.name)
            for doc in documents:
                if doc.display_name == display_name:
                    return doc.name
            return None
        except Exception as e:
            logger.error(f"Error getting document name by display name: {e}")
            return None
