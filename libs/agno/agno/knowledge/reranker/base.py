import asyncio
from typing import List

from pydantic import BaseModel, ConfigDict

from agno.knowledge.document import Document


class Reranker(BaseModel):
    """Base class for rerankers"""

    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)

    def rerank(self, query: str, documents: List[Document]) -> List[Document]:
        raise NotImplementedError

    async def arerank(self, query: str, documents: List[Document]) -> List[Document]:
        """Async rerank. Runs the sync implementation off the event loop, since a
        reranker that calls a provider would otherwise block it."""
        return await asyncio.to_thread(self.rerank, query, documents)
