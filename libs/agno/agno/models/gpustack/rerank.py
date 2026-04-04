"""GPUStack Rerank implementation."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from agno.models.gpustack.base import GPUStackBaseModel
from agno.utils.log import log_debug


@dataclass
class GPUStackRerank(GPUStackBaseModel):
    """GPUStack Rerank model.

    This class implements the reranking API for GPUStack,
    supporting document reranking based on query relevance.

    API Endpoint: /v1/rerank
    """

    id: str = "bge-reranker-v2-m3"  # Model ID on GPUStack
    name: str = "GPUStackRerank"

    # Default parameters
    top_n: Optional[int] = None
    return_documents: Optional[bool] = True

    def rerank(
        self,
        query: str,
        documents: List[Union[str, Dict[str, str]]],
        top_n: Optional[int] = None,
        return_documents: Optional[bool] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Rerank documents based on query relevance.

        Args:
            query: The search query
            documents: List of documents to rerank. Can be strings or dicts with 'text' field
            top_n: Number of top results to return
            return_documents: Whether to return full document text in results

        Returns:
            Dict containing reranked results with scores
        """
        log_debug(f"GPUStack Rerank with model: {self.id}")

        # Format documents
        formatted_docs = []
        for doc in documents:
            if isinstance(doc, str):
                formatted_docs.append({"text": doc})
            elif isinstance(doc, dict) and "text" in doc:
                formatted_docs.append({"text": doc["text"]})
            else:
                raise ValueError(f"Invalid document format: {doc}")

        request_data = {
            "model": self.id,
            "query": query,
            "documents": formatted_docs,
        }

        # Add optional parameters
        if top_n is not None:
            request_data["top_n"] = top_n
        elif self.top_n is not None:
            request_data["top_n"] = self.top_n

        if return_documents is not None:
            request_data["return_documents"] = return_documents
        elif self.return_documents is not None:
            request_data["return_documents"] = self.return_documents

        # Add any additional kwargs
        request_data.update(kwargs)

        response = self._make_request(
            method="POST",
            endpoint="/v1/rerank",
            json_data=request_data,
        )

        return response.json()

    async def arerank(
        self,
        query: str,
        documents: List[Union[str, Dict[str, str]]],
        top_n: Optional[int] = None,
        return_documents: Optional[bool] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Rerank documents asynchronously.

        Args:
            query: The search query
            documents: List of documents to rerank
            top_n: Number of top results to return
            return_documents: Whether to return full document text

        Returns:
            Dict containing reranked results with scores
        """
        log_debug(f"GPUStack Rerank async with model: {self.id}")

        # Format documents
        formatted_docs = []
        for doc in documents:
            if isinstance(doc, str):
                formatted_docs.append({"text": doc})
            elif isinstance(doc, dict) and "text" in doc:
                formatted_docs.append({"text": doc["text"]})
            else:
                raise ValueError(f"Invalid document format: {doc}")

        request_data = {
            "model": self.id,
            "query": query,
            "documents": formatted_docs,
        }

        # Add optional parameters
        if top_n is not None:
            request_data["top_n"] = top_n
        elif self.top_n is not None:
            request_data["top_n"] = self.top_n

        if return_documents is not None:
            request_data["return_documents"] = return_documents
        elif self.return_documents is not None:
            request_data["return_documents"] = self.return_documents

        # Add any additional kwargs
        request_data.update(kwargs)

        response = await self._amake_request(
            method="POST",
            endpoint="/v1/rerank",
            json_data=request_data,
        )

        return response.json()

    def parse_rerank_response(self, response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse rerank response to extract results.

        Returns:
            List of dicts with 'index', 'relevance_score', and optionally 'document'
        """
        results = []

        if "results" in response:
            for result in response["results"]:
                parsed_result = {
                    "index": result.get("index"),
                    "relevance_score": result.get("relevance_score"),
                }

                if "document" in result and result["document"]:
                    parsed_result["document"] = result["document"].get("text", "")

                results.append(parsed_result)

        return results
