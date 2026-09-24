from typing import List, Optional

from pydantic import Field

from agno.knowledge.query_transform.base import QueryTransform
from agno.models.base import Model
from agno.models.message import Message
from agno.utils.log import log_debug, log_warning

DEFAULT_PROMPT = (
    "Write a short passage that answers the question below, as it might appear in a "
    "reference document. Do not hedge, ask for clarification, or mention that you are "
    "uncertain: an invented but plausible answer is what is wanted. Reply with the "
    "passage only.\n\nQuestion: {query}"
)


class HyDE(QueryTransform):
    """Searches with a hypothetical answer instead of the question.

    Questions and the passages that answer them rarely share wording, so a question
    embeds some distance from its own answer. HyDE asks an LLM to invent an answer and
    searches with that, which lands closer to real answers in the same space. The
    invented answer is never shown to the user and does not need to be correct: it only
    has to look like the kind of document being searched for.

    Costs one LLM call per search. If that call fails the original query is used, so a
    provider outage degrades results rather than breaking search.
    """

    # Model used to write the hypothetical answer. Falls back to the model of the agent
    # that triggered the search, then to a default, so this only needs setting to pick a
    # cheaper or faster one.
    model: Optional[Model] = None
    prompt: str = DEFAULT_PROMPT
    # Search with the question and the hypothetical answer together.
    include_query: bool = False
    # Ceiling on the generated passage, so a verbose model cannot blow up the embedding input.
    max_characters: int = Field(default=2000, gt=0)

    def _messages(self, query: str) -> List[Message]:
        return [Message(role="user", content=self.prompt.format(query=query))]

    def _combine(self, query: str, hypothetical: str) -> str:
        passage = hypothetical.strip()[: self.max_characters]
        if not passage:
            return query
        log_debug(f"HyDE generated a hypothetical answer of {len(passage)} characters")
        return f"{query}\n\n{passage}" if self.include_query else passage

    def _resolve_model(self, model: Optional[Model]) -> Optional[Model]:
        """Own model, then the caller's, then a default.

        The default is only reached when Knowledge is searched directly, since an agent
        offers its own model. It is deliberately not tied to the Agent default, which
        lags the model this repository's examples use.
        """
        if self.model is not None:
            return self.model
        if model is not None:
            return model
        try:
            from agno.models.openai import OpenAIResponses
        except ModuleNotFoundError:
            # Unlike an agent, a query transform is an enhancement: searching with the
            # query as asked beats refusing to search at all.
            log_warning(
                "HyDE needs a model to generate a hypothetical answer. Provide a `model` "
                "or install `openai`. Searching with the query as asked."
            )
            return None

        log_debug("HyDE setting default model to OpenAI Responses")
        return OpenAIResponses(id="gpt-5.5")

    def transform(self, query: str, model: Optional[Model] = None) -> str:
        resolved = self._resolve_model(model)
        if resolved is None:
            return query
        try:
            response = resolved.response(messages=self._messages(query))
        except Exception as e:
            # A degraded search beats no search, as with a failing reranker.
            log_warning(f"HyDE could not generate a hypothetical answer, using the query as asked: {e}")
            return query
        return self._combine(query, response.content or "")

    async def atransform(self, query: str, model: Optional[Model] = None) -> str:
        resolved = self._resolve_model(model)
        if resolved is None:
            return query
        try:
            response = await resolved.aresponse(messages=self._messages(query))
        except Exception as e:
            log_warning(f"HyDE could not generate a hypothetical answer, using the query as asked: {e}")
            return query
        return self._combine(query, response.content or "")
