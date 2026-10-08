"""HyDE: searching with a hypothetical answer instead of the question."""

from typing import Any, List, Optional

import pytest

from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.query_transformer.base import QueryTransformer
from agno.knowledge.query_transformer.hyde import HyDE
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
    import inspect

    from agno.agent import _init

    resolved = HyDE()._resolve_model(None)

    assert resolved is not None
    # Asserted against the Agent default rather than a literal, so the two cannot drift.
    assert f'id="{resolved.id}"' in inspect.getsource(_init.set_default_model)


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
    knowledge = Knowledge(vector_db=db, query_transformer=HyDE(model=StubModel()))

    knowledge.search("why did revenue drop?", max_results=3)

    assert db.searched_with == PASSAGE


@pytest.mark.asyncio
async def test_async_knowledge_searches_with_the_transformed_query():
    db = RecordingVectorDb()
    knowledge = Knowledge(vector_db=db, query_transformer=HyDE(model=StubModel()))

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
        query_transformer=HyDE(model=StubModel()),
        reranker=Recorder(),
    )

    knowledge.search("why did revenue drop?", max_results=3)

    assert seen == ["why did revenue drop?"]


def test_a_failing_transform_does_not_break_search():
    class BrokenTransform(QueryTransformer):
        def transform(self, query: str, model: Optional[Any] = None) -> str:
            raise RuntimeError("transform exploded")

    db = RecordingVectorDb()
    knowledge = Knowledge(vector_db=db, query_transformer=BrokenTransform())

    results = knowledge.search("why did revenue drop?", max_results=3)

    assert db.searched_with == "why did revenue drop?"
    assert len(results) == 3


def test_retrieve_offers_the_model_to_the_transform():
    # The agent's search tool goes through retrieve(), not search(), so the model has to
    # reach the transform there too or HyDE silently builds its own default.
    db = RecordingVectorDb()
    knowledge = Knowledge(vector_db=db, query_transformer=HyDE())
    model = StubModel()

    knowledge.retrieve("why did revenue drop?", max_results=3, model=model)

    assert db.searched_with == PASSAGE
    assert model.prompts


@pytest.mark.asyncio
async def test_aretrieve_offers_the_model_to_the_transform():
    db = RecordingVectorDb()
    knowledge = Knowledge(vector_db=db, query_transformer=HyDE())
    model = StubModel()

    await knowledge.aretrieve("why did revenue drop?", max_results=3, model=model)

    assert db.searched_with == PASSAGE


def test_the_agent_retrieval_path_passes_its_model():
    # Guards the wiring in agent/_messages.py: a Knowledge that accepts `model` must be
    # offered the agent's, or HyDE through an Agent never borrows it.
    from agno.utils.knowledge import get_model_kwarg

    model = StubModel()
    knowledge = Knowledge(vector_db=RecordingVectorDb(), query_transformer=HyDE())

    assert get_model_kwarg(knowledge.retrieve, model) == {"model": model}
    assert get_model_kwarg(knowledge.aretrieve, model) == {"model": model}


def test_a_retriever_that_cannot_take_a_model_is_left_alone():
    from agno.utils.knowledge import get_model_kwarg

    def legacy_retriever(query, max_results=None, filters=None):
        return []

    assert get_model_kwarg(legacy_retriever, StubModel()) == {}


def test_the_team_retrieval_path_passes_its_model():
    # Teams retrieve through their own code path, so wiring the Agent one is not enough:
    # a query transformer under a Team would otherwise build its own default model.
    from agno.utils.knowledge import get_model_kwarg

    model = StubModel()
    knowledge = Knowledge(vector_db=RecordingVectorDb(), query_transformer=HyDE())

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


def test_a_custom_prompt_must_contain_the_query_placeholder():
    # A custom prompt replaces the default, so without the placeholder the model is asked
    # to answer a question it was never shown.
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        HyDE(prompt="Write a short passage.")


def test_a_custom_prompt_with_the_placeholder_is_accepted():
    transform = HyDE(prompt="Answer this as a document would: {query}")

    assert transform.prompt == "Answer this as a document would: {query}"


def test_the_run_response_is_forwarded_so_the_llm_call_is_metered():
    # Model.response only accumulates usage when run_response is passed, so without this
    # every search adds an LLM call that run metrics never see.
    seen = {}

    class MeteringModel(StubModel):
        def response(self, messages, **kwargs):  # type: ignore[override]
            seen["run_response"] = kwargs.get("run_response")
            return StubResponse(PASSAGE)

    marker = object()
    HyDE(model=MeteringModel()).transform("q", run_response=marker)

    assert seen["run_response"] is marker


@pytest.mark.asyncio
async def test_the_run_response_is_forwarded_on_the_async_path():
    seen = {}

    class MeteringModel(StubModel):
        async def aresponse(self, messages, **kwargs):  # type: ignore[override]
            seen["run_response"] = kwargs.get("run_response")
            return StubResponse(PASSAGE)

    marker = object()
    await HyDE(model=MeteringModel()).atransform("q", run_response=marker)

    assert seen["run_response"] is marker


def test_knowledge_forwards_the_run_response_to_the_transformer():
    seen = {}

    class Recorder(QueryTransformer):
        def transform(self, query: str, model=None, run_response=None) -> str:
            seen["run_response"] = run_response
            return query

    marker = object()
    knowledge = Knowledge(vector_db=RecordingVectorDb(), query_transformer=Recorder())

    knowledge.search("q", max_results=3, run_response=marker)

    assert seen["run_response"] is marker


def test_retrieve_forwards_the_run_response_to_the_transformer():
    # The add_knowledge_to_context path goes through retrieve(), so a run_response that
    # stops here leaves HyDE's tokens out of the run's metrics.
    seen = {}

    class Recorder(QueryTransformer):
        def transform(self, query: str, model=None, run_response=None) -> str:
            seen["run_response"] = run_response
            return query

    marker = object()
    knowledge = Knowledge(vector_db=RecordingVectorDb(), query_transformer=Recorder())

    knowledge.retrieve("q", max_results=3, run_response=marker)

    assert seen["run_response"] is marker


@pytest.mark.asyncio
async def test_aretrieve_forwards_the_run_response_to_the_transformer():
    seen = {}

    class Recorder(QueryTransformer):
        async def atransform(self, query: str, model=None, run_response=None) -> str:
            seen["run_response"] = run_response
            return query

    marker = object()
    knowledge = Knowledge(vector_db=RecordingVectorDb(), query_transformer=Recorder())

    await knowledge.aretrieve("q", max_results=3, run_response=marker)

    assert seen["run_response"] is marker


def test_the_retrieval_paths_offer_the_run_response():
    # Mirrors the model wiring: a Knowledge that declares run_response must be offered the
    # caller's run, on both the Agent and Team paths.
    from agno.utils.knowledge import get_run_response_kwarg

    marker = object()
    knowledge = Knowledge(vector_db=RecordingVectorDb(), query_transformer=HyDE())

    assert get_run_response_kwarg(knowledge.retrieve, marker) == {"run_response": marker}
    assert get_run_response_kwarg(knowledge.aretrieve, marker) == {"run_response": marker}


def test_a_retriever_that_cannot_take_a_run_response_is_left_alone():
    # A legacy retriever forwarding **kwargs to a narrower search would raise on a kwarg
    # it never declared, and losing metrics attribution is the lesser cost.
    from agno.utils.knowledge import get_run_response_kwarg

    def legacy_retriever(query, max_results=None, filters=None):
        return []

    def variadic_only(query, **kwargs):
        return []

    assert get_run_response_kwarg(legacy_retriever, object()) == {}
    assert get_run_response_kwarg(variadic_only, object()) == {}


def test_every_retrieval_call_site_offers_the_run_response():
    # Guards against wiring one caller and missing its twin, as happened with the Team
    # paths after the Agent ones were done.
    import inspect

    from agno.agent import _messages
    from agno.team import _default_tools

    for module in (_messages, _default_tools):
        source = inspect.getsource(module)
        calls = source.count("retrieve_fn(**retrieve_kwargs)")
        offers = source.count("get_run_response_kwarg(")
        assert offers >= calls, f"{module.__name__} retrieves {calls} times but offers a run {offers} times"


def test_every_knowledge_search_tool_passes_the_run_response():
    # The search tool closures are the path an agent actually takes; each call into
    # get_relevant_docs_from_knowledge has to carry the run it belongs to.
    import inspect

    from agno.agent import _default_tools as agent_default_tools
    from agno.team import _default_tools as team_default_tools

    for module in (agent_default_tools, team_default_tools):
        source = inspect.getsource(module.create_knowledge_search_tool)
        # "docs = " anchors on the call itself, not the docstring that names the function.
        calls = source.count("docs = ")
        passes = source.count("run_response=run_response")
        assert passes == calls, f"{module.__name__} retrieves {calls} times but passes the run {passes} times"


def test_the_default_model_is_built_once_per_instance():
    # Each model carries an HTTP client, and this resolves on every search.
    transform = HyDE()

    first = transform._resolve_model(None)
    second = transform._resolve_model(None)

    assert first is second


def test_the_cached_default_is_a_public_field():
    transform = HyDE()

    assert "default_model" in type(transform).model_fields
    resolved = transform._resolve_model(None)

    assert transform.default_model is resolved


def test_a_preset_default_model_is_used_without_building_one():
    preset = StubModel()
    transform = HyDE(default_model=preset)

    assert transform._resolve_model(None) is preset


def test_caching_the_default_does_not_shadow_a_supplied_model():
    transform = HyDE()
    transform._resolve_model(None)  # populate the cache

    caller_model = StubModel()

    assert transform._resolve_model(caller_model) is caller_model


def test_a_prompt_with_other_braces_does_not_raise():
    # str.format treats any brace as a field, so a JSON example in the prompt used to
    # raise KeyError and get swallowed as a generation failure.
    transform = HyDE(prompt='Answer {query}. Reply as {"answer": "..."}')

    content = transform._messages("why did revenue drop?")[0].content

    assert "why did revenue drop?" in content
    assert '{"answer": "..."}' in content


def test_every_placeholder_occurrence_is_substituted():
    transform = HyDE(prompt="{query} -- restated: {query}")

    content = transform._messages("why?")[0].content

    assert content == "why? -- restated: why?"


def test_truncation_prefers_a_sentence_boundary():
    # A fragment left mid-word goes straight into the text being embedded.
    passage = "Revenue declined because enterprise renewals slipped. Churn also rose sharply."

    result = HyDE(max_characters=60)._combine("q", passage)

    assert result == "Revenue declined because enterprise renewals slipped."


def test_truncation_falls_back_to_a_word_boundary():
    passage = "Revenue declined because enterprise renewals slipped and churn rose"

    result = HyDE(max_characters=30)._combine("q", passage)

    assert result == "Revenue declined because"


def test_a_passage_under_the_limit_is_untouched():
    assert HyDE(max_characters=500)._combine("q", "Short answer.") == "Short answer."


def test_a_passage_with_no_break_is_still_capped():
    assert HyDE(max_characters=5)._combine("q", "abcdefghij") == "abcde"


def test_a_lexical_store_warns_when_the_question_is_dropped(monkeypatch):
    # The keyword half only has the words it is given, so replacing the query weakens it.
    import agno.knowledge.knowledge as knowledge_module

    messages: List[str] = []
    monkeypatch.setattr(knowledge_module, "log_warning", lambda message, *a, **k: messages.append(str(message)))

    from agno.vectordb.search import SearchType

    class HybridStore(RecordingVectorDb):
        search_type = SearchType.hybrid

    Knowledge(vector_db=HybridStore(), query_transformer=HyDE())

    assert any("keyword half" in message for message in messages)


def test_keeping_the_question_does_not_warn(monkeypatch):
    import agno.knowledge.knowledge as knowledge_module

    messages: List[str] = []
    monkeypatch.setattr(knowledge_module, "log_warning", lambda message, *a, **k: messages.append(str(message)))

    from agno.vectordb.search import SearchType

    class HybridStore(RecordingVectorDb):
        search_type = SearchType.hybrid

    Knowledge(vector_db=HybridStore(), query_transformer=HyDE(include_query=True))

    assert not any("keyword half" in message for message in messages)


def test_a_vector_only_store_does_not_warn(monkeypatch):
    import agno.knowledge.knowledge as knowledge_module

    messages: List[str] = []
    monkeypatch.setattr(knowledge_module, "log_warning", lambda message, *a, **k: messages.append(str(message)))

    from agno.vectordb.search import SearchType

    class VectorStore(RecordingVectorDb):
        search_type = SearchType.vector

    Knowledge(vector_db=VectorStore(), query_transformer=HyDE())

    assert not any("keyword half" in message for message in messages)


def test_keyword_search_is_not_transformed():
    # Lexical search ANDs the query terms, so a generated passage requires every one of
    # its words in one document: nothing matches and the store returns insertion order.
    from agno.vectordb.search import SearchType

    class KeywordStore(RecordingVectorDb):
        search_type = SearchType.keyword

    db = KeywordStore()
    knowledge = Knowledge(vector_db=db, query_transformer=HyDE(model=StubModel()))

    knowledge.search("why did revenue drop?", max_results=3)

    assert db.searched_with == "why did revenue drop?"


@pytest.mark.asyncio
async def test_keyword_search_is_not_transformed_async():
    from agno.vectordb.search import SearchType

    class KeywordStore(RecordingVectorDb):
        search_type = SearchType.keyword

    db = KeywordStore()
    knowledge = Knowledge(vector_db=db, query_transformer=HyDE(model=StubModel()))

    await knowledge.asearch("why did revenue drop?", max_results=3)

    assert db.searched_with == "why did revenue drop?"


def test_a_per_call_keyword_search_type_also_skips_the_transform():
    # search(search_type=...) is written onto the store before the check runs, so this
    # covers the override path end to end rather than the helper's own argument.
    from agno.vectordb.search import SearchType

    class VectorStore(RecordingVectorDb):
        search_type = SearchType.vector

    db = VectorStore()
    knowledge = Knowledge(vector_db=db, query_transformer=HyDE(model=StubModel()))

    knowledge.search("why did revenue drop?", max_results=3, search_type="keyword")

    assert db.searched_with == "why did revenue drop?"


def test_hybrid_search_is_still_transformed():
    from agno.vectordb.search import SearchType

    class HybridStore(RecordingVectorDb):
        search_type = SearchType.hybrid

    db = HybridStore()
    knowledge = Knowledge(vector_db=db, query_transformer=HyDE(model=StubModel(), include_query=True))

    knowledge.search("why did revenue drop?", max_results=3)

    assert PASSAGE in (db.searched_with or "")


def _page_knowledge(transformer):
    """Knowledge backed by a stub page store, recording what search_pages received."""
    from agno.knowledge.page import SearchResult

    recorded: dict = {}
    knowledge = Knowledge.__new__(Knowledge)
    knowledge.page_store = object()
    knowledge.max_results = 10
    knowledge.reranker = None
    knowledge.query_transformer = transformer

    def fake_search_pages(query, *, limit=10, **kwargs):
        recorded["query"] = query
        # Absent rather than None when there is nothing to add, so the call shape for
        # callers without a transformer is unchanged.
        recorded["alternatives"] = kwargs.get("alternatives", "ABSENT")
        return SearchResult(results=[], partial=False)

    knowledge.search_pages = fake_search_pages  # type: ignore[method-assign]
    knowledge._page_documents = staticmethod(lambda result: [])  # type: ignore[method-assign]
    return knowledge, recorded


def test_page_search_keeps_the_question_and_adds_the_passage():
    # Page search ranks each phrasing separately and fuses, so replacing the query would
    # throw away the lexical ranking of the question as asked.
    knowledge, recorded = _page_knowledge(HyDE(model=StubModel()))

    knowledge.search("why did revenue drop?", max_results=3)

    assert recorded["query"] == "why did revenue drop?"
    assert recorded["alternatives"] == [PASSAGE]


def test_page_search_sends_no_alternatives_when_the_query_is_unchanged():
    class Identity(QueryTransformer):
        def transform(self, query: str, model=None, run_response=None) -> str:
            return query

    knowledge, recorded = _page_knowledge(Identity())

    knowledge.search("why did revenue drop?", max_results=3)

    assert recorded["alternatives"] == "ABSENT"


def test_page_search_without_a_transformer_sends_no_alternatives():
    knowledge, recorded = _page_knowledge(None)

    knowledge.search("why did revenue drop?", max_results=3)

    assert recorded["query"] == "why did revenue drop?"
    assert recorded["alternatives"] == "ABSENT"
