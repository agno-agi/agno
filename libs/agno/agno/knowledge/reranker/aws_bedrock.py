from os import getenv
from typing import Any, Dict, List, Literal, Optional

from pydantic import ConfigDict, Field

from agno.knowledge.document import Document
from agno.knowledge.reranker.base import Reranker
from agno.utils.log import logger

try:
    from boto3 import client as AwsClient
    from boto3.session import Session
    from botocore.exceptions import ClientError
except ImportError:
    raise ImportError("`boto3` not installed. Please install it via `pip install boto3`.")


# Model ID constants
AMAZON_RERANK_V1 = "amazon.rerank-v1:0"
COHERE_RERANK_V3_5 = "cohere.rerank-v3-5:0"

# Type alias for supported models
RerankerModel = Literal["amazon.rerank-v1:0", "cohere.rerank-v3-5:0"]


class AwsBedrockReranker(Reranker):
    """
    AWS Bedrock reranker supporting Amazon Rerank 1.0 and Cohere Rerank 3.5 models.

    This reranker uses the unified Bedrock Rerank API (bedrock-agent-runtime)
    which provides a consistent interface for both model providers.

    To use this reranker, you need to either:
    1. Set the following environment variables:
       - AWS_ACCESS_KEY_ID
       - AWS_SECRET_ACCESS_KEY
       - AWS_REGION
    2. Or provide a boto3 Session object

    Args:
        model (str): The model ID to use. Options:
            - 'amazon.rerank-v1:0' (Amazon Rerank 1.0)
            - 'cohere.rerank-v3-5:0' (Cohere Rerank 3.5)
            Default is 'cohere.rerank-v3-5:0'.
        top_n (Optional[int]): Number of top results to return after reranking.
            If None, returns all documents reranked.
        aws_region (Optional[str]): The AWS region to use.
        aws_access_key_id (Optional[str]): The AWS access key ID to use.
        aws_secret_access_key (Optional[str]): The AWS secret access key to use.
        session (Optional[Session]): A boto3 Session object for authentication.
        additional_model_request_fields (Optional[Dict]): Additional model-specific
            parameters to pass in the request (e.g., Cohere-specific options).

    Example:
        ```python
        from agno.knowledge.reranker.aws_bedrock import AwsBedrockReranker

        # Using Cohere Rerank 3.5 (default)
        reranker = AwsBedrockReranker(
            model="cohere.rerank-v3-5:0",
            top_n=5,
            aws_region="us-west-2",
        )

        # Using Amazon Rerank 1.0
        reranker = AwsBedrockReranker(
            model="amazon.rerank-v1:0",
            top_n=10,
            aws_region="us-west-2",
        )

        # Rerank documents
        reranked_docs = reranker.rerank(query="What is machine learning?", documents=docs)
        ```

    Note:
        - Amazon Rerank 1.0 is NOT available in us-east-1 (N. Virginia).
          Use Cohere Rerank 3.5 in that region.
        - Maximum 1000 documents per request.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)

    model: str = Field(default=COHERE_RERANK_V3_5, description="Reranker model ID")
    top_n: Optional[int] = Field(default=None, description="Number of top results to return")

    aws_region: Optional[str] = Field(default=None, description="AWS region")
    aws_access_key_id: Optional[str] = Field(default=None, description="AWS access key ID")
    aws_secret_access_key: Optional[str] = Field(default=None, description="AWS secret access key")
    session: Optional[Session] = Field(default=None, description="Boto3 session", exclude=True)

    additional_model_request_fields: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional model-specific request parameters",
    )

    _client: Optional[AwsClient] = None

    @property
    def client(self) -> AwsClient:
        """
        Returns a bedrock-agent-runtime client for the Rerank API.

        Returns:
            AwsClient: An instance of the bedrock-agent-runtime client.
        """
        if self._client is not None:
            return self._client

        if self.session:
            self._client = self.session.client("bedrock-agent-runtime")
            return self._client

        aws_access_key_id = self.aws_access_key_id or getenv("AWS_ACCESS_KEY_ID")
        aws_secret_access_key = self.aws_secret_access_key or getenv("AWS_SECRET_ACCESS_KEY")
        aws_region = self.aws_region or getenv("AWS_REGION")

        if not aws_access_key_id or not aws_secret_access_key:
            # Fall back to default credential chain
            self._client = AwsClient(
                service_name="bedrock-agent-runtime",
                region_name=aws_region,
            )
        else:
            self._client = AwsClient(
                service_name="bedrock-agent-runtime",
                region_name=aws_region,
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
            )

        return self._client

    def _get_model_arn(self) -> str:
        """
        Constructs the full model ARN for the reranker model.

        Returns:
            str: The model ARN.
        """
        region = self.aws_region or getenv("AWS_REGION", "us-west-2")
        return f"arn:aws:bedrock:{region}::foundation-model/{self.model}"

    def _build_sources(self, documents: List[Document]) -> List[Dict[str, Any]]:
        """
        Convert Document objects to Bedrock Rerank API source format.

        Args:
            documents: List of Document objects to convert.

        Returns:
            List of RerankSource objects for the API.
        """
        sources = []
        for doc in documents:
            # Use text format for document content
            source = {
                "type": "INLINE",
                "inlineDocumentSource": {
                    "type": "TEXT",
                    "textDocument": {
                        "text": doc.content,
                    },
                },
            }
            sources.append(source)
        return sources

    def _rerank(self, query: str, documents: List[Document]) -> List[Document]:
        """
        Internal method to perform reranking via Bedrock Rerank API.

        Args:
            query: The query string to rank documents against.
            documents: List of Document objects to rerank.

        Returns:
            List of Document objects sorted by relevance score.
        """
        if not documents:
            return []

        # Validate top_n
        top_n = self.top_n
        if top_n is not None and top_n <= 0:
            logger.warning(f"top_n should be a positive integer, got {self.top_n}, setting top_n to None")
            top_n = None

        # Build the request
        rerank_request: Dict[str, Any] = {
            "queries": [
                {
                    "type": "TEXT",
                    "textQuery": {
                        "text": query,
                    },
                }
            ],
            "sources": self._build_sources(documents),
            "rerankingConfiguration": {
                "type": "BEDROCK_RERANKING_MODEL",
                "bedrockRerankingConfiguration": {
                    "modelConfiguration": {
                        "modelArn": self._get_model_arn(),
                    },
                },
            },
        }

        # Add numberOfResults if top_n is specified
        if top_n is not None:
            rerank_request["rerankingConfiguration"]["bedrockRerankingConfiguration"]["numberOfResults"] = top_n

        # Add additional model request fields if provided
        if self.additional_model_request_fields:
            rerank_request["rerankingConfiguration"]["bedrockRerankingConfiguration"]["modelConfiguration"][
                "additionalModelRequestFields"
            ] = self.additional_model_request_fields

        # Call the Rerank API
        response = self.client.rerank(**rerank_request)

        # Process results
        reranked_docs: List[Document] = []
        results = response.get("results", [])

        for result in results:
            index = result.get("index")
            relevance_score = result.get("relevanceScore")

            if index is not None and index < len(documents):
                doc = documents[index]
                doc.reranking_score = relevance_score
                reranked_docs.append(doc)

        # Results from API are already sorted by relevance, but ensure sorting
        reranked_docs.sort(
            key=lambda x: x.reranking_score if x.reranking_score is not None else float("-inf"),
            reverse=True,
        )

        return reranked_docs

    def rerank(self, query: str, documents: List[Document]) -> List[Document]:
        """
        Rerank documents based on their relevance to a query.

        Args:
            query: The query string to rank documents against.
            documents: List of Document objects to rerank.

        Returns:
            List of Document objects sorted by relevance score (highest first).
            Each document will have its `reranking_score` attribute set.
        """
        try:
            return self._rerank(query=query, documents=documents)
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.error(f"AWS Bedrock Rerank API error ({error_code}): {error_message}. Returning original documents.")
            return documents
        except Exception as e:
            logger.error(f"Error reranking documents: {e}. Returning original documents.")
            return documents


class CohereBedrockReranker(AwsBedrockReranker):
    """
    Convenience class for Cohere Rerank 3.5 on AWS Bedrock.

    This is a pre-configured AwsBedrockReranker using the Cohere Rerank 3.5 model.

    Example:
        ```python
        reranker = CohereBedrockReranker(top_n=5, aws_region="us-west-2")
        reranked_docs = reranker.rerank(query="What is AI?", documents=docs)
        ```
    """

    model: str = Field(default=COHERE_RERANK_V3_5)


class AmazonReranker(AwsBedrockReranker):
    """
    Convenience class for Amazon Rerank 1.0 on AWS Bedrock.

    This is a pre-configured AwsBedrockReranker using the Amazon Rerank 1.0 model.

    Note: Amazon Rerank 1.0 is NOT available in us-east-1 (N. Virginia).

    Example:
        ```python
        reranker = AmazonReranker(top_n=5, aws_region="us-west-2")
        reranked_docs = reranker.rerank(query="What is AI?", documents=docs)
        ```
    """

    model: str = Field(default=AMAZON_RERANK_V1)
