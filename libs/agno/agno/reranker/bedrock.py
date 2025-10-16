import json
from os import getenv
from typing import Any, List, Optional

from agno.document import Document
from agno.reranker.base import Reranker
from agno.utils.log import logger

try:
    import boto3
    from boto3.session import Session
    from botocore.exceptions import ClientError
except ImportError:
    raise ImportError("`boto3` not installed. Please install using `pip install boto3`.")


class BedrockReranker(Reranker):
    model: str = "cohere.rerank-v3-5:0"
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    aws_region: Optional[str] = None
    session: Optional[Session] = None
    top_n: Optional[int] = None

    # Private attributes for caching
    client: Optional[Any] = None

    def _get_client(self) -> Any:
        if self.client is not None:
            return self.client

        if self.session:
            self.client = self.session.client("bedrock-runtime")
            return self.client

        self.aws_access_key_id = self.aws_access_key_id or getenv("AWS_ACCESS_KEY_ID")
        self.aws_secret_access_key = self.aws_secret_access_key or getenv("AWS_SECRET_ACCESS_KEY")
        self.aws_region = self.aws_region or getenv("AWS_REGION")

        if not self.aws_access_key_id or not self.aws_secret_access_key:
            raise ValueError(
                "AWS credentials not found. Please set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY keys",
            )

        if not self.aws_region:
            raise ValueError(
                "AWS region not found. Please set AWS_REGION key",
            )

        self.client = boto3.client(
            "bedrock-runtime",
            region_name=self.aws_region,
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
        )
        return self.client

    def _rerank(self, query: str, documents: List[Document]) -> List[Document]:
        # Validate input documents and top_n
        if not documents:
            return []

        top_n = self.top_n
        # Ensure top_n is a positive integer and less than the number of documents.
        # If top_n is greater than or equal to the number of documents, set top_n to the length of documents.
        # Note: valid top_n must be less than len(documents)
        if not top_n or top_n <= 0 or top_n > len(documents):
            logger.warning(
                f"top_n should be a positive integer and less than the number of documents. Setting top_n to {len(documents)}"
            )
            top_n = len(documents)

        _docs: list[str] = [doc.content for doc in documents]
        _body = {
            "query": query,
            "documents": _docs,
            "top_n": top_n,
        }

        try:
            client = self._get_client()
            response = client.invoke_model(
                modelId=self.model,
                body=json.dumps(_body),
            )
            results = json.loads(response.get("body").read())["results"]
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            raise ValueError(
                f"AWS Bedrock error [{error_code}]: {error_message}",
            ) from e

        compressed_docs: list[Document] = []
        for r in results:
            doc = documents[r["index"]]
            doc.reranking_score = r["relevance_score"]
            compressed_docs.append(doc)

        # Order by relevance score
        compressed_docs.sort(
            key=lambda x: x.reranking_score if x.reranking_score is not None else float("-inf"),
            reverse=True,
        )

        # Limit to top_n if specified
        if top_n:
            compressed_docs = compressed_docs[:top_n]

        return compressed_docs

    def rerank(self, query: str, documents: List[Document]) -> List[Document]:
        try:
            return self._rerank(query=query, documents=documents)
        except ValueError as e:
            logger.error(f"AWS Bedrock reranking error: {e}. Returning original documents")
            return documents
        except Exception as e:
            logger.error(f"Unexpected error during reranking: {e}. Returning original documents")
            return documents
