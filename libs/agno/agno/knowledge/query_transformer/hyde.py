from typing import Any, List, Optional

from pydantic import Field, field_validator, model_validator

from agno.knowledge.query_transformer.base import QueryTransformer
from agno.models.base import Model
from agno.models.message import Message
from agno.utils.log import log_debug, log_info, log_warning

DEFAULT_PROMPT = (
    "Write a short passage that answers the question below, as it might appear in a "
    "reference document. Do not hedge, ask for clarification, or mention that you are "
    "uncertain: an invented but plausible answer is what is wanted. Reply with the "
    "passage only.\n\nQuestion: {query}"
)


class HyDE(QueryTransformer):
    """Searches with a hypothetical answer instead of the question.

    Questions and the passages that answer them rarely share wording, so a question
    embeds some distance from its own answer. HyDE asks an LLM to invent an answer and
    searches with that, which lands closer to real answers in the same space. The
    invented answer is never shown to the user and does not need to be correct: it only
    has to look like the kind of document being searched for.

    Costs one LLM call per search. If that call fails the original query is used, so a
    provider outage degrades results rather than breaking search.
    """

    # Model used to write the hypothetical answer. Defaults at init to the same model Agent
    # and Team default to, so this only needs setting to pick a cheaper or faster one.
    model: Optional[Model] = None
    # Replaces DEFAULT_PROMPT rather than adding to it, so a custom prompt carries its own
    # instruction not to hedge. Must contain {query}.
    prompt: str = DEFAULT_PROMPT
    # Search with the question and the hypothetical answer together.
    include_query: bool = False
    # Ceiling on the generated passage, so a verbose model cannot blow up the embedding input.
    max_characters: int = Field(default=2000, gt=0)

    @field_validator("prompt")
    @classmethod
    def _require_query_placeholder(cls, value: str) -> str:
        # Without it the model is asked to answer a question it was never shown.
        if "{query}" not in value:
            raise ValueError("prompt must contain the {query} placeholder")
        return value

    def _messages(self, query: str) -> List[Message]:
        # replace, not format: a prompt carrying other braces (a JSON example, say) would
        # raise KeyError, and the validator has already required the placeholder.
        return [Message(role="user", content=self.prompt.replace("{query}", query))]

    def _truncate(self, passage: str) -> str:
        """Trim to max_characters on a sentence break, else a word break.

        Slicing mid-word leaves a fragment in the text being embedded, which is the one
        thing the embedding is built from.
        """
        if len(passage) <= self.max_characters:
            return passage
        window = passage[: self.max_characters]
        sentence_end = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
        if sentence_end > 0:
            return window[: sentence_end + 1]
        word_end = window.rfind(" ")
        return window[:word_end] if word_end > 0 else window

    def _combine(self, query: str, hypothetical: str) -> str:
        passage = self._truncate(hypothetical.strip())
        if not passage:
            return query
        log_debug(f"HyDE generated a hypothetical answer of {len(passage)} characters")
        return f"{query}\n\n{passage}" if self.include_query else passage

    @model_validator(mode="after")
    def _set_default_model(self) -> "HyDE":
        # Resolved once here rather than per search, so there is one model field with no
        # second place a model can come from. Mirrors Agent and Team.
        if self.model is None:
            try:
                from agno.models.openai import OpenAIResponses
            except ModuleNotFoundError as e:
                raise ImportError(
                    "HyDE uses `openai` as the default model provider. Please provide a `model` or install `openai`."
                ) from e

            log_info("HyDE setting default model to OpenAI Responses")
            self.model = OpenAIResponses(id="gpt-5.4")
        return self

    def transform(self, query: str, run_response: Optional[Any] = None) -> str:
        try:
            response = self.model.response(messages=self._messages(query), run_response=run_response)  # type: ignore[union-attr]
        except Exception as e:
            # A degraded search beats no search, as with a failing reranker.
            log_warning(f"HyDE could not generate a hypothetical answer, using the query as asked: {e}")
            return query
        return self._combine(query, response.content or "")

    async def atransform(self, query: str, run_response: Optional[Any] = None) -> str:
        try:
            response = await self.model.aresponse(messages=self._messages(query), run_response=run_response)  # type: ignore[union-attr]
        except Exception as e:
            log_warning(f"HyDE could not generate a hypothetical answer, using the query as asked: {e}")
            return query
        return self._combine(query, response.content or "")
