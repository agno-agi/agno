"""Background extraction compares learnings within the scope where it saves."""

from types import SimpleNamespace

import pytest

from agno.learn.config import LearnedKnowledgeConfig
from agno.learn.stores.learned_knowledge import LearnedKnowledgeStore
from agno.models.message import Message


class _RecordingModel:
    def __init__(self):
        self.messages = None

    def __deepcopy__(self, memo):
        return self

    def response(self, messages, **kwargs):
        self.messages = messages
        return SimpleNamespace(tool_executions=[], response_usage=None)

    async def aresponse(self, messages, **kwargs):
        return self.response(messages, **kwargs)


class _Knowledge:
    def __init__(self):
        self.filters = None
        self.results = [
            {"title": "alice insight", "learning": "alice observation", "namespace": "user", "user_id": "alice"},
            {"title": "bob insight", "learning": "bob observation", "namespace": "user", "user_id": "bob"},
            {"title": "global insight", "learning": "global observation", "namespace": "global"},
            {"title": "engineering insight", "learning": "engineering observation", "namespace": "engineering"},
        ]

    def search(self, query, max_results, filters=None):
        self.filters = filters
        # Exercise the store's post-filter as well as the filters sent to the backend.
        return self.results[:max_results]

    async def asearch(self, query, max_results, filters=None):
        return self.search(query, max_results, filters)


@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize(
    "configured_namespace,namespace,expected_title,expected_filters",
    [
        ("user", None, "alice insight", {"namespace": "user", "user_id": "alice"}),
        ("global", None, "global insight", {"namespace": "global"}),
        ("engineering", None, "engineering insight", {"namespace": "engineering"}),
        ("global", "user", "alice insight", {"namespace": "user", "user_id": "alice"}),
        ("user", "engineering", "engineering insight", {"namespace": "engineering"}),
        ("user", "global", "global insight", {"namespace": "global"}),
    ],
)
async def test_extraction_scopes_existing_learnings(
    use_async, configured_namespace, namespace, expected_title, expected_filters
):
    knowledge = _Knowledge()
    model = _RecordingModel()
    store = LearnedKnowledgeStore(
        config=LearnedKnowledgeConfig(knowledge=knowledge, model=model, namespace=configured_namespace)
    )
    messages = [Message(role="user", content="Keep the useful insight from this conversation.")]

    if use_async:
        await store.aextract_and_save(messages=messages, user_id="alice", namespace=namespace)
    else:
        store.extract_and_save(messages=messages, user_id="alice", namespace=namespace)

    assert model.messages is not None
    prompt = "\n".join(message.content for message in model.messages)
    assert expected_title in prompt
    for result in knowledge.results:
        if result["title"] != expected_title:
            assert result["title"] not in prompt
    assert knowledge.filters == expected_filters
