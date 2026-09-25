import asyncio
from typing import Optional

from pydantic import BaseModel, ConfigDict

from agno.models.base import Model


class QueryTransform(BaseModel):
    """Base class for query transforms.

    Rewrites the search query before it reaches the vector db, for strategies where the
    question as asked is not the best thing to search with. A reranker reorders results
    after the search; this changes what is searched for.

    ``model`` is the model the caller has available, passed by Knowledge when an agent
    supplies one. A transform that needs an LLM should prefer its own configured model
    and fall back to this.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)

    def transform(self, query: str, model: Optional[Model] = None) -> str:
        """Return the query to search with. Returning ``query`` unchanged is valid."""
        raise NotImplementedError

    async def atransform(self, query: str, model: Optional[Model] = None) -> str:
        """Async transform. Runs the sync implementation off the event loop, since a
        transform that calls a provider would otherwise block it."""
        return await asyncio.to_thread(self.transform, query, model)
