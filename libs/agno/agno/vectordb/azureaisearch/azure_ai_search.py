import ast
from hashlib import md5
from typing import Any, Optional

# Azure AI Search SDK imports
try:
    from azure.core.credentials import AzureKeyCredential
    from azure.core.exceptions import ResourceNotFoundError
    from azure.search.documents import SearchClient
    from azure.search.documents.indexes import SearchIndexClient
    from azure.search.documents.indexes.models import (
        ExhaustiveKnnAlgorithmConfiguration,
        ExhaustiveKnnParameters,
        HnswAlgorithmConfiguration,
        HnswParameters,
        SearchableField,
        SearchField,
        SearchFieldDataType,
        SearchIndex,
        SemanticConfiguration,
        SemanticField,
        SemanticPrioritizedFields,
        SemanticSearch,
        SimpleField,
        VectorSearch,
        VectorSearchAlgorithmKind,
        VectorSearchAlgorithmMetric,
        VectorSearchProfile,
    )
    from azure.search.documents.models import VectorizedQuery
except ImportError:
    raise ImportError(
        "`azure-identity` or `azure-search-documents` package is not installed. Please install them via `pip install azure-identity` and `pip install azure-search-documents`."
    )

from agno.document.base import Document
from agno.embedder.base import Embedder
from agno.utils.log import logger
from agno.vectordb.base import VectorDb
from agno.vectordb.search import SearchType


class AzureAISearch(VectorDb):
    def __init__(
        self,
        endpoint: str,
        api_key: str,
        index_name: str,
        embedder: Optional[Embedder] = None,
        search_type: SearchType = SearchType.vector,
    ):
        # Azure Search attributes
        self.endpoint = endpoint
        self.api_key = api_key
        self.index_name = index_name

        # Initialize Azure clients
        self.credential = AzureKeyCredential(api_key)
        self.index_client = SearchIndexClient(endpoint=self.endpoint, credential=self.credential)
        self.search_client = SearchClient(
            endpoint=self.endpoint, index_name=self.index_name, credential=self.credential
        )

        # Embedder for embedding document contents
        if embedder is None:
            from agno.embedder.azure_openai import AzureOpenAIEmbedder

            embedder = AzureOpenAIEmbedder()
        self.embedder: Embedder = embedder
        self.dimensions: Optional[int] = self.embedder.dimensions

        # Search type setup
        self.search_type = search_type

    def create(self) -> None:
        """Creates an Azure Cognitive Search index with vector search capabilities."""
        # Base fields
        fields = [
            SimpleField(
                name="id",
                type="Edm.String",
                key=True,
                filterable=True,
            ),
            SearchableField(
                name="chunk",
                type="Edm.String",
                analyzer_name="en.lucene",
            ),
            SearchField(
                name="embedding",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                vector_search_dimensions=self.dimensions,
                vector_search_profile_name="myExhaustiveKnnProfile",
                hidden=False,
            ),
            SimpleField(
                name="metadata",
                type="Edm.String",
            ),
            SimpleField(
                name="doc_id",
                type="Edm.String",
                filterable=True,
            ),
            SimpleField(
                name="page_number",
                type="Edm.Int32",
            ),
            SimpleField(
                name="usage",
                type="Edm.String",
            ),
        ]

        # Configure vector search with both HNSW and exhaustiveKnn
        vector_search = VectorSearch(
            algorithms=[
                HnswAlgorithmConfiguration(
                    name="myHnsw",
                    kind=VectorSearchAlgorithmKind.HNSW,
                    parameters=HnswParameters(
                        m=4,
                        ef_construction=400,
                        ef_search=500,
                        metric=VectorSearchAlgorithmMetric.COSINE,
                    ),
                ),
                ExhaustiveKnnAlgorithmConfiguration(
                    name="myExhaustiveKnn",
                    kind=VectorSearchAlgorithmKind.EXHAUSTIVE_KNN,
                    parameters=ExhaustiveKnnParameters(
                        metric=VectorSearchAlgorithmMetric.COSINE,
                    ),
                ),
            ],
            profiles=[
                VectorSearchProfile(
                    name="myHnswProfile",
                    algorithm_configuration_name="myHnsw",
                ),
                VectorSearchProfile(
                    name="myExhaustiveKnnProfile",
                    algorithm_configuration_name="myExhaustiveKnn",
                ),
            ],
        )

        # Configure semantic search
        semantic_config = SemanticConfiguration(
            name="mySemanticConfig",
            prioritized_fields=SemanticPrioritizedFields(content_fields=[SemanticField(field_name="chunk")]),
        )

        semantic_search = SemanticSearch(configurations=[semantic_config])

        # Create the index
        index = SearchIndex(
            name=self.index_name,
            fields=fields,
            vector_search=vector_search,
            semantic_search=semantic_search,
        )

        try:
            self.index_client.get_index(self.index_name)
        except Exception:
            self.index_client.create_index(index)

    def insert(
        self,
        documents: list[Document],
        filters: Optional[dict[str, Any]] = None,
        batch_size: int = 10,
    ) -> None:
        """
        Insert documents into Azure AI Search index.

        Args:
            documents (List[Document]): List of documents to insert
            filters (Optional[Dict[str, Any]]): Filters to apply while inserting documents
            batch_size (int): Batch size for inserting documents
        """
        logger.info(f"Inserting {len(documents)} documents")

        azure_docs = []
        for document in documents:
            try:
                # Embed the document if not already embedded
                document.embed(embedder=self.embedder)
            except Exception as e:
                logger.error(f"Error embedding document {document.name}: {str(e)}")
                raise

            # Clean content and generate doc_id
            cleaned_content = document.content.replace("\x00", "\ufffd")
            doc_id = md5(cleaned_content.encode()).hexdigest()

            # Create Azure Search document
            azure_doc = {
                "id": doc_id,
                "chunk": cleaned_content,
                "embedding": document.embedding,
                "metadata": str(document.meta_data) if document.meta_data else "",
                "doc_id": document.name,
                "page_number": document.meta_data.get("page") if document.meta_data else "",
                "usage": str(document.usage) if document.usage else "",
            }

            azure_docs.append(azure_doc)
            logger.info(f"Prepared document: {document.name} ({document.meta_data})")

        # Upload documents in batches
        for i in range(0, len(azure_docs), batch_size):
            batch = azure_docs[i : i + batch_size]
            try:
                self.search_client.upload_documents(documents=batch)
                logger.info(f"Uploaded batch of {len(batch)} documents")
            except Exception as e:
                logger.info(f"Error uploading documents batch: {str(e)}")
                raise

        logger.info(f"Uploaded total of {len(azure_docs)} documents")

    def doc_exists(self, document: Document) -> bool:
        """
        Checks for the existence of a document in the index by its unique id.
        """
        # Clean content and compute document id as done during insertion
        cleaned_content = document.content.replace("\x00", "\ufffd")
        doc_id = md5(cleaned_content.encode()).hexdigest()

        try:
            # Attempt to retrieve the document by its unique key
            _ = self.search_client.get_document(key=doc_id)
            return True
        except ResourceNotFoundError:
            return False
        except Exception as e:
            logger.error(f"Error checking if document exists: {str(e)}")
            raise

    def name_exists(self, name: str) -> bool:
        """
        Checks if a document with the given name exists in the index.
        """
        try:
            # Use a wildcard search with a filter on the 'doc_id' field,
            # which corresponds to the document name.
            results = self.search_client.search(
                search_text="*",
                filter=f"doc_id eq '{name}'",
                select=["doc_id"],
                include_total_count=True,
            )
            # If there is at least one result, the document exists.
            if results.get_count() and results.get_count() > 0:
                return True

            # Alternatively, iterate through results (if get_count is unavailable)
            for _ in results:
                return True

            return False

        except Exception as e:
            logger.error(f"Error checking if name exists: {e}")
            raise

    def id_exists(self, id: str) -> bool:
        """
        Checks if a document with the given id exists in the index.
        """
        try:
            # Attempt to fetch the document by its unique key.
            self.search_client.get_document(key=id)
            return True
        except ResourceNotFoundError:
            return False
        except Exception as e:
            logger.error(f"Error checking if id exists: {e}")
            raise

    def _document_to_dict(self, document: Document) -> dict[str, Any]:
        """
        Converts a Document object to a dictionary formatted for Azure Search.
        """
        # Clean the content to ensure no null characters
        cleaned_content = document.content.replace("\x00", "\ufffd")

        # Generate a unique document id using MD5 hash of the cleaned content,
        # unless an id is already provided in the Document.
        doc_id = document.id if document.id is not None else md5(cleaned_content.encode()).hexdigest()

        return {
            "id": doc_id,
            "chunk": cleaned_content,
            "embedding": document.embedding,
            "metadata": str(document.meta_data) if document.meta_data else "",
            "doc_id": document.name,  # using 'name' as document identifier in the index
            "page_number": document.meta_data.get("page")
            if document.meta_data and "page" in document.meta_data
            else "",
            "usage": str(document.usage) if document.usage else "",
        }

    def _parse_document(self, result: dict[str, Any]) -> Document:
        """
        Parses a document dictionary returned from Azure Search into a Document object.
        """
        # Extract the stored fields from the Azure Search result.
        content = result.get("chunk", "")
        doc_id = result.get("id")
        name = result.get("doc_id")
        embedding = result.get("embedding")
        usage_str = result.get("usage", "")
        metadata_str = result.get("metadata", "")
        page_number = result.get("page_number", "")

        # Convert metadata string back to a dictionary if possible.
        meta_data: dict[str, Any] = {}
        if metadata_str:
            try:
                meta_data = ast.literal_eval(metadata_str)
                if not isinstance(meta_data, dict):
                    meta_data = {"metadata": meta_data}
            except Exception:
                meta_data = {"metadata": metadata_str}

        # Incorporate the page number into the metadata (if present).
        if page_number:
            meta_data["page"] = page_number

        # Convert usage string back to a dictionary if possible.
        usage: dict[str, Any] = {}
        if usage_str:
            try:
                usage = ast.literal_eval(usage_str)
                if not isinstance(usage, dict):
                    usage = {"usage": usage}
            except Exception:
                usage = {"usage": usage_str}

        # Construct and return the Document.
        return Document(
            content=content,
            id=doc_id,
            name=name,
            meta_data=meta_data,
            embedding=embedding,
            usage=usage,
        )

    def upsert_available(self) -> bool:
        """
        Indicates that upsert functionality is available.
        """
        return True

    def upsert(self, documents: list[Document], filters: Optional[dict[str, Any]] = None) -> None:
        """
        Upsert documents into the database.

        Args:
            documents (List[Document]): List of documents to upsert
            filters (Optional[Dict[str, Any]]): Filters to apply while upserting
        """
        logger.info("Redirecting the request to insert")
        self.insert(documents)

    def search(self, query: str, limit: int = 5, filters: Optional[dict[str, Any]] = None) -> list[Document]:
        """
        Perform a search based on the configured search type.

        Args:
            query (str): The search query.
            limit (int): Maximum number of results to return.
            filters (Optional[Dict[str, Any]]): Filters to apply to the search.

        Returns:
            List[Document]: List of matching documents.
        """
        if self.search_type == SearchType.vector:
            logger.info(f"Redirecting the request to {self.search_type} search")
            return self.vector_search(query, limit)
        elif self.search_type == SearchType.keyword:
            logger.info(f"Redirecting the request to {self.search_type} search")
            return self.keyword_search(query, limit)
        elif self.search_type == SearchType.hybrid:
            logger.info(f"Redirecting the request to {self.search_type} search")
            return self.hybrid_search(query, limit)
        else:
            logger.error(f"Invalid search type '{self.search_type}'.")
            return []

    def vector_search(self, query: str, limit: int = 5) -> list[Document]:
        """
        Performs a vector search by converting the query into an embedding vector.
        The query embedding is passed to the search service to rank documents by vector similarity.
        """
        try:
            # Generate the query embedding using the embedder
            query_embedding = self.embedder.get_embedding(query)
            logger.info("Query embedding generated successfully")

            vector_query = VectorizedQuery(
                vector=query_embedding,  # the query vector
                k_nearest_neighbors=limit,  # number of nearest neighbors to return (maps to "k")
                fields="embedding",  # field in the index storing document embeddings
                weight=1.0,  # default relative weight; adjust if you have multiple queries
            )
            logger.info("Vector query generated successfully")

            # Execute the search query
            results = self.search_client.search(
                search_text="*",  # using a wildcard to match all documents
                vector_queries=[vector_query],
                top=limit,
            )
            logger.info("Search query executed successfully")

            # Parse the results into Document objects
            documents = [self._parse_document(result) for result in results]

            logger.info(f"Vector search for query '{query}' returned {len(documents)} documents.")
            return documents

        except Exception as e:
            logger.error(f"Error performing vector search: {e}")
            raise

    def keyword_search(self, query: str, limit: int = 5) -> list[Document]:
        """
        Performs a traditional keyword search over the index using full-text search.
        """
        try:
            # Execute a full-text search query
            results = self.search_client.search(search_text=query, top=limit)
            logger.info("Keyword search query executed successfully")

            # Parse the results into Document objects.
            documents = [self._parse_document(result) for result in results]
            logger.info(f"Keyword search for query '{query}' returned {len(documents)} documents.")
            return documents

        except Exception as e:
            logger.error(f"Error performing keyword search: {e}")
            raise

    def hybrid_search(self, query: str, limit: int = 5) -> list[Document]:
        """
        Performs a hybrid search by combining a
        full-text search with a vector similarity search.
        The query is used both as the text search term and
        to generate an embedding for the vector query.
        The results from both subqueries are merged and
        re-ranked by Azure AI Search.
        """
        try:
            # Generate the query embedding using the configured embedder.
            query_embedding = self.embedder.get_embedding(query)
            logger.info("Query embedding generated successfully")

            # Create a vector query instance.
            # Ensure that 'embedding' matches the name of the vector field in your index.
            vector_query = VectorizedQuery(
                vector=query_embedding,
                k_nearest_neighbors=limit,
                fields="embedding",  # adjust if your vector field name is different
                weight=1.0,  # adjust relative weight if combining multiple subqueries
            )
            logger.info("Vector query generated successfully")

            # Execute the search with both text and vector components.
            results = self.search_client.search(
                search_text=query,  # full-text component
                vector_queries=[vector_query],  # vector component
                top=limit,
            )
            logger.info("Hybrid search query executed successfully")

            # Parse the results into Document objects.
            documents = [self._parse_document(result) for result in results]
            logger.info(f"Hybrid search for query '{query}' returned {len(documents)} documents.")
            return documents

        except Exception as e:
            logger.error(f"Error performing hybrid search: {e}")
            raise

    def drop(self) -> None:
        """
        Deletes the index.
        """
        try:
            self.index_client.delete_index(self.index_name)
            logger.info(f"Index '{self.index_name}' deleted.")
        except ResourceNotFoundError:
            logger.warning(f"Index '{self.index_name}' not found when attempting to delete.")
        except Exception as e:
            logger.error(f"Error deleting index '{self.index_name}': {e}")
            raise

    def exists(self) -> bool:
        """
        Checks if the index exists.
        """
        try:
            self.index_client.get_index(self.index_name)
            return True
        except ResourceNotFoundError:
            return False
        except Exception as e:
            logger.error(f"Error checking if index '{self.index_name}' exists: {e}")
            raise

    def optimize(self) -> None:
        """
        Optimization is not explicitly supported in Azure Cognitive Search.
        This method is a no-op.
        """
        pass

    def delete(self) -> bool:
        """
        Deletes the index and returns whether the deletion was successful.
        """
        try:
            self.drop()
            # After attempting to drop, check if the index still exists
            if not self.exists():
                logger.info(f"Index '{self.index_name}' deletion confirmed.")
                return True
            else:
                logger.warning(f"Index '{self.index_name}' still exists after deletion attempt.")
                return False
        except Exception as e:
            logger.error(f"Error during deletion of index '{self.index_name}': {e}")
            raise

    def get_embedding(self, text: str) -> list[float]:
        """
        Placeholder method to convert a text query to an embedding vector.
        In production, replace this with an actual call to an embedding service (e.g. Azure OpenAI).
        """
        raise NotImplementedError("The embedding function must be implemented to use vector_search.")
