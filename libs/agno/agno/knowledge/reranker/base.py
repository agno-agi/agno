import asyncio
from inspect import signature
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from agno.knowledge.document import Document


class Reranker(BaseModel):
    """Base class for rerankers"""

    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)

    # Candidates fetched per requested result. Reranking is worth its cost because it
    # rescues documents the vector search ranked below the cutoff, so the default asks
    # for a wider pool; set it to 1 for a reranker that only needs to reorder.
    candidate_multiplier: int = Field(default=3, ge=1)
    # Ceiling on the widened fetch, so a large request cannot turn one search into an
    # unbounded scan.
    max_candidates: int = Field(default=100, ge=1)

    def search_limit(self, max_results: int) -> int:
        """The number of candidates the vector db should return for this reranker."""
        # The ceiling caps the widening, never the caller's own request: clamping below
        # max_results would return fewer documents than were asked for.
        return max(min(max_results * self.candidate_multiplier, self.max_candidates), max_results)

    def rerank(self, query: str, documents: List[Document], limit: Optional[int] = None) -> List[Document]:
        """Reorder documents. ``limit`` is the count the caller keeps, which a reranker
        that selects a subset can use to stop early; scoring rerankers ignore it."""
        raise NotImplementedError

    def accepts_limit(self) -> bool:
        """Whether this reranker's ``rerank`` takes the caller's kept count.

        Rerankers written against the older two-argument signature, including ones
        outside this repo, are still called without it.
        """
        try:
            return "limit" in signature(self.rerank).parameters
        except (TypeError, ValueError):
            return False

    async def arerank(self, query: str, documents: List[Document], limit: Optional[int] = None) -> List[Document]:
        """Async rerank. Runs the sync implementation off the event loop, since a
        reranker that calls a provider would otherwise block it."""
        if self.accepts_limit():
            return await asyncio.to_thread(self.rerank, query, documents, limit)
        return await asyncio.to_thread(self.rerank, query, documents)
