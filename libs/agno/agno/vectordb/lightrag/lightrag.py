from hashlib import md5
from typing import Any, Dict, List, Optional


from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.reranker.base import Reranker
from agno.utils.log import log_debug, log_info, log_warning, log_error
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance
from agno.vectordb.search import SearchType

DEFAULT_DENSE_VECTOR_NAME = "dense"
DEFAULT_SPARSE_VECTOR_NAME = "sparse"
DEFAULT_SPARSE_MODEL = "Qdrant/bm25"
DEFAULT_SERVER_URL = "http://localhost:9621"


class LightRag(VectorDb):
    """
    LightRAG VectorDB implementation
    """

    def __init__(
        self,
        server_url: str = DEFAULT_SERVER_URL,
    ):
        self.server_url = server_url

    def create(self):
        pass

    def insert(self, content: str, metadata: Dict[str, Any]):
        pass


    async def _insert_text(self, text: str) -> Dict[str, Any]:
        """Insert text into the LightRAG server."""
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.lightrag_server_url}/documents/text",
                json={"text": text},
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            result = response.json()
            log_debug(f"Text insertion result: {result}")
            return result

    def _is_valid_url(self, url: str) -> bool:
        """Helper to check if URL is valid."""
        if not any(url.endswith(ext) for ext in self.SUPPORTED_EXTENSIONS):
            log_error(f"Unsupported URL: {url}. Supported file types: {', '.join(self.SUPPORTED_EXTENSIONS)}")
            return False
        return True