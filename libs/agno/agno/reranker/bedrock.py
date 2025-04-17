import json
import os
from typing import Any, Dict, List, Optional

from agno.document import Document
from agno.reranker.base import Reranker
from agno.utils.log import logger

try:
    import boto3
except ImportError:
    raise ImportError("`boto3` not installed. Please install using `pip install boto3`.")


class BedrockReranker(Reranker):
    model: str = "cohere.rerank-v3-5:0"
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    region_name: Optional[str] = None
    profile_name: Optional[str] = None
    bedrock_session: Optional[boto3.Session] = None
    top_n: Optional[int] = None
    api_version: Optional[int] = 2  # Only for model cohere.rerank-v3-5:0

    @property
    def session(self) -> boto3.Session:
        if self.bedrock_session:
            return self.bedrock_session

        _client_params: Dict[str, Any] = {}
        _client_params["aws_access_key_id"] = self.aws_access_key_id or os.getenv("AWS_ACCESS_KEY_ID")
        _client_params["aws_secret_access_key"] = self.aws_secret_access_key or os.getenv("AWS_SECRET_ACCESS_KEY")
        _client_params["region_name"] = self.region_name or os.getenv("AWS_REGION")
        _client_params["profile_name"] = self.profile_name or os.getenv("AWS_PROFILE")
        return boto3.Session(**_client_params)

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
        if self.model == "cohere.rerank-v3-5:0":
            _body["api_version"] = self.api_version

        response = self.session.client("bedrock-runtime").invoke_model(
            modelId=self.model,
            body=json.dumps(_body),
        )
        results = json.loads(response.get("body").read())["results"]

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
        except Exception as e:
            logger.error(f"Error reranking documents: {e}. Returning original documents")
            return documents
