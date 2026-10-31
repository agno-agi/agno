import asyncio
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class QueryTransformer(BaseModel):
    """Base class for query transformers.

    Rewrites the search query before it reaches the vector db, for strategies where the
    question as asked is not the best thing to search with. A reranker reorders results
    after the search; this changes what is searched for.

    A transform that needs an LLM configures its own model, the way Agent and Team do.
    ``run_response`` is passed on so an LLM call a transform makes is counted in the run's
    metrics rather than going unreported.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)

    def transform(self, query: str, run_response: Optional[Any] = None) -> str:
        """Return the query to search with. Returning ``query`` unchanged is valid."""
        raise NotImplementedError

    async def atransform(self, query: str, run_response: Optional[Any] = None) -> str:
        """Async transform. Runs the sync implementation off the event loop, since a
        transform that calls a provider would otherwise block it."""
        return await asyncio.to_thread(self.transform, query, run_response)
