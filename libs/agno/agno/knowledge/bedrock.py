from typing import Any, AsyncIterator, Dict, Iterator, List, Optional

from agno.document import Document
from agno.knowledge.agent import AgentKnowledge
from agno.utils.log import logger

try:
    import boto3
except ImportError:
    raise ImportError("The `boto3` package is not installed. Please install it via `pip install boto3`.")


class BedrockKnowledgeBase(AgentKnowledge):
    knowledge_base_id: str
    region_name: str = "us-east-1"
    client: Optional[Any] = None
    # Required by AgentKnowledge - set to a dummy value since Bedrock manages this externally
    vector_db: Any = "bedrock_managed"

    def __init__(self, **data):
        super().__init__(**data)
        if self.client is None:
            self.client = boto3.client("bedrock-agent-runtime", region_name=self.region_name)
        # Set vector_db to indicate this is externally managed
        self.vector_db = "bedrock_managed"

    @property
    def document_lists(self) -> Iterator[List[Document]]:
        """Iterator that yields lists of documents in the knowledge base"""
        # Bedrock KB is externally managed, return empty iterator
        return iter([])

    @property
    def async_document_lists(self) -> AsyncIterator[List[Document]]:
        """Async iterator that yields lists of documents in the knowledge base"""

        async def _async_generator():
            # Bedrock KB is externally managed, return empty async iterator
            return
            yield  # Make it an async generator

        return _async_generator()

    def search(
        self, query: str, num_documents: Optional[int] = None, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """
        Returns relevant documents matching the query using Bedrock Knowledge Base.

        Args:
            query (str): The query string to search for.
            num_documents (Optional[int]): The maximum number of documents to return. Defaults to None.
            filters (Optional[Dict[str, Any]]): Filters to apply to the search. Defaults to None.

        Returns:
            List[Document]: A list of relevant documents matching the query.
        """
        try:
            _num_documents = num_documents or self.num_documents
            # Prepare retrieval configuration
            retrieval_config: Dict[str, Any] = {"vectorSearchConfiguration": {"numberOfResults": _num_documents}}
            if filters:
                retrieval_config["vectorSearchConfiguration"]["filter"] = filters

            # Call Bedrock Knowledge Base retrieve API
            if self.client is None:
                raise ValueError("Bedrock client not initialized")

            response = self.client.retrieve(
                knowledgeBaseId=self.knowledge_base_id,
                retrievalQuery={"text": query},
                retrievalConfiguration=retrieval_config,
            )

            # Convert Bedrock response to Agno Documents
            documents = []
            retrieval_results = response.get("retrievalResults", [])

            for result in retrieval_results:
                content = result.get("content", {}).get("text", "")
                metadata = {
                    "score": result.get("score", 0.0),
                    "location": result.get("location", {}),
                    "source": "bedrock_knowledge_base",
                }

                # Add any additional metadata from the result
                if "metadata" in result:
                    metadata.update(result["metadata"])

                documents.append(Document(content=content, meta_data=metadata))

            return documents

        except Exception as e:
            logger.error(f"Error retrieving documents from Bedrock Knowledge Base: {e}")
            return []

    def load(
        self,
        recreate: bool = False,
        upsert: bool = True,
        skip_existing: bool = True,
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Bedrock Knowledge Base is managed externally.
        This method logs a warning as loading is not supported.
        """
        logger.warning(
            "BedrockKnowledgeBase.load() not supported - Knowledge Base is managed externally via AWS Console or APIs"
        )

    def exists(self) -> bool:
        """
        Check if the Bedrock Knowledge Base exists and is accessible.

        Returns:
            bool: True if the knowledge base exists and is accessible, False otherwise.
        """
        try:
            # Use bedrock-agent client to check knowledge base existence
            agent_client = boto3.client("bedrock-agent", region_name=self.region_name)
            agent_client.get_knowledge_base(knowledgeBaseId=self.knowledge_base_id)
            return True
        except Exception as e:
            logger.error(f"Knowledge Base {self.knowledge_base_id} not accessible: {e}")
            return False
