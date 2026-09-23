"""HyDE: searching with a hypothetical answer instead of the question."""

from typing import Any, List, Optional

import pytest

from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.query_transform.base import QueryTransform
from agno.knowledge.query_transform.hyde import HyDE
from agno.models.base import Model

PASSAGE = "Revenue fell because enterprise renewals slipped into the next quarter."


class StubResponse:
    def __init__(self, content: Optional[str]):
        self.content = content


class StubModel(Model):
    """Records the prompt it was asked for and returns a fixed passage."""

    def __init__(self, content: Optional[str] = PASSAGE):
        super().__init__(id="hyde-test", name="hyde-test", provider="test")
        self.content = content
        self.prompts: List[str] = []

    def response(self, messages, **kwargs) -> StubResponse:  # type: ignore[override]
        self.prompts.append(messages[0].content)
        return StubResponse(self.content)

    async def aresponse(self, messages, **kwargs) -> StubResponse:  # type: ignore[override]
        return self.response(messages, **kwargs)

    # HyDE calls response()/aresponse(), so the provider hooks below are never reached.
    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> Any:
        return response

    def _parse_provider_response_delta(self, response: Any) -> Any:
        return response


class FailingModel(StubModel):
    def response(self, messages, **kwargs) -> StubResponse:  # type: ignore[override]
        raise RuntimeError("provider unavailable")

    async def aresponse(self, messages, **kwargs) -> StubResponse:  # type: ignore[override]
        raise RuntimeError("provider unavailable")


class RecordingVectorDb:
    """Records the query the vector db was actually searched with."""

    def __init__(self):
        self.searched_with: Optional[str] = None
        self.reranker = None

    def exists(self) -> bool:
        return True

    def search(self, query: str, limit: int = 5, filters=None) -> List[Document]:
        self.searched_with = query
        return [Document(id=str(i), content=f"doc {i}") for i in range(min(limit, 5))]

    async def async_search(self, query: str, limit: int = 5, filters=None) -> List[Document]:
        return self.search(query=query, limit=limit, filters=filters)


def test_the_hypothetical_answer_replaces_the_query():
    model = StubModel()

    assert HyDE(model=model).transform("why did revenue drop?") == PASSAGE


def test_the_question_is_in_the_prompt():
    model = StubModel()

    HyDE(model=model).transform("why did revenue drop?")

    assert "why did revenue drop?" in model.prompts[0]


def test_include_query_keeps_the_question_alongside_the_passage():
    result = HyDE(model=StubModel(), include_query=True).transform("why did revenue drop?")

    assert result.startswith("why did revenue drop?")
    assert PASSAGE in result


def test_a_configured_model_wins_over_the_caller_model():
    own = StubModel("own model passage")
    caller = StubModel("caller model passage")

    assert HyDE(model=own).transform("q", model=caller) == "own model passage"
    assert not caller.prompts


def test_the_caller_model_is_used_when_none_is_configured():
    caller = StubModel()

    assert HyDE().transform("q", model=caller) == PASSAGE


def test_no_model_anywhere_falls_back_to_the_default_model():
    # Direct knowledge.search() passes no model, so HyDE builds the same default Agent
    # and Team use rather than silently doing nothing.
    resolved = HyDE()._resolve_model(None)

    assert resolved is not None
    assert resolved.id == "gpt-5.5"


def test_an_unavailable_provider_searches_with_the_query_as_asked(monkeypatch):
    # Without openai installed a transform degrades, where an agent would refuse to run.
    import builtins

    real_import = builtins.__import__

    def no_openai(name, *args, **kwargs):
        if name == "agno.models.openai":
            raise ModuleNotFoundError("No module named 'openai'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_openai)

    assert HyDE().transform("why did revenue drop?") == "why did revenue drop?"


def test_a_provider_failure_falls_back_to_the_query():
    assert HyDE(model=FailingModel()).transform("why did revenue drop?") == "why did revenue drop?"


@pytest.mark.parametrize("content", [None, "", "   "])
def test_an_empty_passage_falls_back_to_the_query(content):
    assert HyDE(model=StubModel(content)).transform("why did revenue drop?") == "why did revenue drop?"


def test_a_long_passage_is_truncated():
    model = StubModel("x" * 5000)

    assert len(HyDE(model=model, max_characters=100).transform("q")) == 100


def test_max_characters_must_be_positive():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        HyDE(max_characters=0)


@pytest.mark.asyncio
async def test_atransform_matches_transform():
    assert await HyDE(model=StubModel()).atransform("why did revenue drop?") == PASSAGE


@pytest.mark.asyncio
async def test_async_provider_failure_falls_back_to_the_query():
    assert await HyDE(model=FailingModel()).atransform("q") == "q"


def test_knowledge_searches_with_the_transformed_query():
    db = RecordingVectorDb()
    knowledge = Knowledge(vector_db=db, query_transform=HyDE(model=StubModel()))

    knowledge.search("why did revenue drop?", max_results=3)

    assert db.searched_with == PASSAGE


@pytest.mark.asyncio
async def test_async_knowledge_searches_with_the_transformed_query():
    db = RecordingVectorDb()
    knowledge = Knowledge(vector_db=db, query_transform=HyDE(model=StubModel()))

    await knowledge.asearch("why did revenue drop?", max_results=3)

    assert db.searched_with == PASSAGE


def test_without_a_transform_the_query_reaches_the_vector_db_unchanged():
    db = RecordingVectorDb()
    knowledge = Knowledge(vector_db=db)

    knowledge.search("why did revenue drop?", max_results=3)

    assert db.searched_with == "why did revenue drop?"


def test_the_reranker_scores_against_the_original_question():
    # Reranking against an invented passage would score documents on a stand-in for the
    # question rather than the question itself.
    seen: List[str] = []

    from agno.knowledge.reranker.base import Reranker

    class Recorder(Reranker):
        def rerank(self, query: str, documents: List[Document], limit: Optional[int] = None) -> List[Document]:
            seen.append(query)
            return documents

    knowledge = Knowledge(
        vector_db=RecordingVectorDb(),
        query_transform=HyDE(model=StubModel()),
        reranker=Recorder(),
    )

    knowledge.search("why did revenue drop?", max_results=3)

    assert seen == ["why did revenue drop?"]


def test_a_failing_transform_does_not_break_search():
    class BrokenTransform(QueryTransform):
        def transform(self, query: str, model: Optional[Any] = None) -> str:
            raise RuntimeError("transform exploded")

    db = RecordingVectorDb()
    knowledge = Knowledge(vector_db=db, query_transform=BrokenTransform())

    results = knowledge.search("why did revenue drop?", max_results=3)

    assert db.searched_with == "why did revenue drop?"
    assert len(results) == 3


def test_retrieve_offers_the_model_to_the_transform():
    # The agent's search tool goes through retrieve(), not search(), so the model has to
    # reach the transform there too or HyDE silently builds its own default.
    db = RecordingVectorDb()
    knowledge = Knowledge(vector_db=db, query_transform=HyDE())
    model = StubModel()

    knowledge.retrieve("why did revenue drop?", max_results=3, model=model)

    assert db.searched_with == PASSAGE
    assert model.prompts


@pytest.mark.asyncio
async def test_aretrieve_offers_the_model_to_the_transform():
    db = RecordingVectorDb()
    knowledge = Knowledge(vector_db=db, query_transform=HyDE())
    model = StubModel()

    await knowledge.aretrieve("why did revenue drop?", max_results=3, model=model)

    assert db.searched_with == PASSAGE


def test_the_agent_retrieval_path_passes_its_model():
    # Guards the wiring in agent/_messages.py: a Knowledge that accepts `model` must be
    # offered the agent's, or HyDE through an Agent never borrows it.
    from agno.utils.knowledge import get_model_kwarg

    model = StubModel()
    knowledge = Knowledge(vector_db=RecordingVectorDb(), query_transform=HyDE())

    assert get_model_kwarg(knowledge.retrieve, model) == {"model": model}
    assert get_model_kwarg(knowledge.aretrieve, model) == {"model": model}


def test_a_retriever_that_cannot_take_a_model_is_left_alone():
    from agno.utils.knowledge import get_model_kwarg

    def legacy_retriever(query, max_results=None, filters=None):
        return []

    assert get_model_kwarg(legacy_retriever, StubModel()) == {}


def test_the_team_retrieval_path_passes_its_model():
    # Teams retrieve through their own code path, so wiring the Agent one is not enough:
    # a query transform under a Team would otherwise build its own default model.
    from agno.utils.knowledge import get_model_kwarg

    model = StubModel()
    knowledge = Knowledge(vector_db=RecordingVectorDb(), query_transform=HyDE())

    assert get_model_kwarg(knowledge.retrieve, model) == {"model": model}
    assert get_model_kwarg(knowledge.aretrieve, model) == {"model": model}


def test_every_retrieval_call_site_offers_the_model():
    # Guards against wiring one caller and missing its twin, which is what happened with
    # the Team paths after the Agent ones were done.
    import inspect

    from agno.agent import _messages
    from agno.team import _default_tools

    for module in (_messages, _default_tools):
        source = inspect.getsource(module)
        calls = source.count("retrieve_fn(**retrieve_kwargs)")
        offers = source.count("get_model_kwarg(")
        assert offers >= calls, f"{module.__name__} retrieves {calls} times but offers a model {offers} times"


def test_a_legacy_knowledge_that_forwards_kwargs_is_not_broken():
    # A custom Knowledge predating `model` often forwards **kwargs to a narrower search.
    # Offering it a model it never declared would raise on every retrieval.
    from agno.utils.knowledge import get_model_kwarg

    class LegacyKnowledge:
        def search(self, query: str, max_results=None, filters=None, user_id=None):
            return []

        def retrieve(self, query: str, **kwargs):
            return self.search(query=query, **kwargs)

    knowledge = LegacyKnowledge()
    kwargs = get_model_kwarg(knowledge.retrieve, StubModel())

    assert kwargs == {}
    # The call the agent would make must still work.
    assert knowledge.retrieve("q", **kwargs) == []


def test_kwargs_alone_is_not_consent_to_receive_a_model():
    from agno.utils.knowledge import get_model_kwarg

    def variadic_only(query, **kwargs):
        return []

    def declares_model(query, model=None, **kwargs):
        return []

    assert get_model_kwarg(variadic_only, StubModel()) == {}
    assert get_model_kwarg(declares_model, StubModel()) != {}
