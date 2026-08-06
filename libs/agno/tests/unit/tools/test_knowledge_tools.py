"""Tests for per-call KnowledgeTools namespace isolation."""

import asyncio
import time
from copy import deepcopy
from threading import Lock
from typing import Any, Dict, List, Optional

import pytest

from agno.agent import Agent
from agno.agent._tools import determine_tools_for_model
from agno.db.in_memory import InMemoryDb
from agno.db.sqlite import SqliteDb
from agno.fs.errors import InvalidPathError
from agno.knowledge.content import ContentStatus
from agno.knowledge.document import Document
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.registry import Registry
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.session import AgentSession
from agno.tools.function import Function, FunctionCall
from agno.tools.knowledge import KnowledgeTools
from agno.tools.studio import StudioTools
from agno.vectordb.base import VectorDb


class MemoryVectorDb(VectorDb):
    """Small shared vector store that enforces metadata filters."""

    supports_namespaced_knowledge = True

    def __init__(self):
        super().__init__(name="memory-vector-db")
        self.records: List[tuple[str, Document]] = []
        self._lock = Lock()

    def create(self) -> None:
        pass

    async def async_create(self) -> None:
        pass

    def name_exists(self, name: str) -> bool:
        return any(document.name == name for _, document in self.records)

    async def async_name_exists(self, name: str) -> bool:
        return self.name_exists(name)

    def id_exists(self, id: str) -> bool:
        return any(document.id == id for _, document in self.records)

    def content_hash_exists(self, content_hash: str) -> bool:
        return any(stored_hash == content_hash for stored_hash, _ in self.records)

    def content_hash_is_indexed(self, content_hash: str, expected_count: int = 1) -> bool:
        return sum(stored_hash == content_hash for stored_hash, _ in self.records) == expected_count

    def insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            for document in documents:
                stored = deepcopy(document)
                if filters:
                    stored.meta_data.update(filters)
                self.records.append((content_hash, stored))

    async def async_insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.insert(content_hash, documents, filters)

    def upsert_available(self) -> bool:
        return True

    def upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            self.records = [(h, d) for h, d in self.records if h != content_hash]
        self.insert(content_hash, documents, filters)

    async def async_upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.upsert(content_hash, documents, filters)

    def search(self, query: str, limit: int = 5, filters: Optional[Any] = None) -> List[Document]:
        matches: List[Document] = []
        for _, document in self.records:
            if query.lower() not in (document.content or "").lower():
                continue
            if isinstance(filters, dict) and any(
                document.meta_data.get(key) != value for key, value in filters.items()
            ):
                continue
            matches.append(deepcopy(document))
        return matches[:limit]

    async def async_search(self, query: str, limit: int = 5, filters: Optional[Any] = None) -> List[Document]:
        return self.search(query, limit, filters)

    def drop(self) -> None:
        self.records = []

    async def async_drop(self) -> None:
        self.drop()

    def exists(self) -> bool:
        return True

    async def async_exists(self) -> bool:
        return True

    def delete(self) -> bool:
        self.drop()
        return True

    def delete_by_id(self, id: str) -> bool:
        before = len(self.records)
        self.records = [(h, d) for h, d in self.records if d.id != id]
        return len(self.records) != before

    def delete_by_name(self, name: str) -> bool:
        before = len(self.records)
        self.records = [(h, d) for h, d in self.records if d.name != name]
        return len(self.records) != before

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        before = len(self.records)
        self.records = [
            (h, d) for h, d in self.records if not all(d.meta_data.get(key) == value for key, value in metadata.items())
        ]
        return len(self.records) != before

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        for _, document in self.records:
            if document.content_id == content_id:
                document.meta_data.update(metadata)

    def delete_by_content_id(self, content_id: str) -> bool:
        before = len(self.records)
        self.records = [(h, d) for h, d in self.records if d.content_id != content_id]
        return len(self.records) != before

    def get_supported_search_types(self) -> List[str]:
        return ["vector"]


class SlowKnowledge(Knowledge):
    """Expose quota races by pausing after each namespace snapshot."""

    def get_content(self, *args, **kwargs):
        result = super().get_content(*args, **kwargs)
        time.sleep(0.05)
        return result

    async def aget_content(self, *args, **kwargs):
        result = await super().aget_content(*args, **kwargs)
        await asyncio.sleep(0.05)
        return result


class FailingVectorDb(MemoryVectorDb):
    """Vector store that can expose swallowed indexing failures."""

    def __init__(self):
        super().__init__()
        self.fail = True

    def upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        if self.fail:
            raise RuntimeError("index unavailable")
        super().upsert(content_hash, documents, filters)

    async def async_upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        if self.fail:
            raise RuntimeError("index unavailable")
        await super().async_upsert(content_hash, documents, filters)


class SilentFailVectorDb(MemoryVectorDb):
    """Vector store that swallows writes without creating an index record."""

    def __init__(self):
        super().__init__()
        self.fail = True

    def upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.fail:
            super().upsert(content_hash, documents, filters)

    async def async_upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.fail:
            await super().async_upsert(content_hash, documents, filters)


class PartialVectorDb(MemoryVectorDb):
    """Vector store that silently indexes only the first text chunk."""

    def upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().upsert(content_hash, documents[:1], filters)

    async def async_upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.upsert(content_hash, documents, filters)


class VerificationFailVectorDb(MemoryVectorDb):
    """Vector store that commits a vector but cannot verify it afterward."""

    def __init__(self):
        super().__init__()
        self.fail_verification = True
        self.cleaned_content_ids: List[str] = []

    def content_hash_is_indexed(self, content_hash: str, expected_count: int = 1) -> bool:
        if self.fail_verification:
            return False
        return super().content_hash_is_indexed(content_hash, expected_count)

    def delete_by_content_id(self, content_id: str) -> bool:
        self.cleaned_content_ids.append(content_id)
        super().delete_by_content_id(content_id)
        return True


@pytest.fixture
def knowledge_stack():
    vector_db = MemoryVectorDb()
    vector_db.embedder = OpenAIEmbedder()
    contents_db = InMemoryDb()
    knowledge = Knowledge(name="Registry knowledge", vector_db=vector_db, contents_db=contents_db)
    toolkit = KnowledgeTools(
        name="agent_knowledge",
        knowledge=knowledge,
        namespace="corpora/{agent_id}",
        enable_think=False,
        enable_analyze=False,
        enable_add=True,
    )
    return toolkit, knowledge, vector_db, contents_db


def _context() -> RunContext:
    return RunContext(run_id="run-1", session_id="session-1")


class TestNamespaceResolution:
    def test_resolves_fresh_view_without_mutating_template(self, knowledge_stack):
        toolkit, knowledge, vector_db, contents_db = knowledge_stack
        alpha = Agent(id="Alpha", name="Alpha", telemetry=False)

        resolved = toolkit._resolved(_context(), alpha, None)

        assert resolved is not knowledge
        assert resolved.name == "corpora/alpha"
        assert resolved.isolate_vector_search is True
        assert resolved.vector_db is vector_db
        assert resolved.contents_db is contents_db
        assert resolved.vector_db.embedder is vector_db.embedder
        assert resolved.vector_db.embedder.api_key is None
        assert resolved._enforce_content_isolation is True
        assert knowledge.name == "Registry knowledge"
        assert knowledge.isolate_vector_search is False
        assert knowledge._enforce_content_isolation is False

    def test_missing_agent_context_fails_closed(self, knowledge_stack):
        toolkit, _, _, _ = knowledge_stack

        result = toolkit.search_knowledge(_context(), "anything")

        assert (
            result
            == "Error searching knowledge base: this agent's knowledge requires agent_id for this run and none was provided."
        )

    @pytest.mark.parametrize("spoofed_agent", [{"id": "victim"}, "victim"])
    def test_spoofed_json_identity_fails_closed_through_hook_path(self, knowledge_stack, spoofed_agent):
        toolkit, _, _, _ = knowledge_stack
        function = toolkit.functions["search_knowledge"]
        function.process_entrypoint()
        function._agent = Agent(id="real-agent", name="Real", telemetry=False)
        function._run_context = _context()

        def passthrough(function_name, function_call, arguments):
            return function_call(**arguments)

        function.tool_hooks = [passthrough]
        call = FunctionCall(
            function=function,
            arguments={"query": "anything", "agent": spoofed_agent},
        )

        result = call.execute()

        assert result.status == "success"
        assert result.result == (
            "Error searching knowledge base: this agent's knowledge requires agent_id for this run and none was provided."
        )

    def test_spoof_without_hooks_fails_before_entrypoint(self, knowledge_stack):
        toolkit, _, _, _ = knowledge_stack
        function = toolkit.functions["search_knowledge"]
        function.process_entrypoint()
        function._agent = Agent(id="real-agent", telemetry=False)
        function._run_context = _context()

        result = FunctionCall(
            function=function,
            arguments={"query": "anything", "agent": {"id": "victim"}},
        ).execute()

        assert result.status == "failure"
        assert "multiple values for keyword argument 'agent'" in result.error

    def test_write_identity_spoof_fails_closed_without_writing(self, knowledge_stack):
        toolkit, _, _, contents_db = knowledge_stack
        function = toolkit.functions["add_text_to_knowledge"]
        function.process_entrypoint()
        function._agent = Agent(id="real-agent", telemetry=False)
        function._run_context = _context()

        def passthrough(function_name, function_call, arguments):
            return function_call(**arguments)

        function.tool_hooks = [passthrough]
        result = FunctionCall(
            function=function,
            arguments={
                "name": "spoofed",
                "text_content": "victim secret",
                "agent": {"id": "victim"},
            },
        ).execute()

        assert result.status == "success"
        assert result.result == (
            "Error adding text to knowledge: this agent's knowledge requires agent_id for this run and none was provided."
        )
        assert contents_db._knowledge == []

    def test_invalid_template_is_rejected(self):
        knowledge = Knowledge(name="K", vector_db=MemoryVectorDb(), contents_db=InMemoryDb())

        with pytest.raises(InvalidPathError, match="unknown placeholder"):
            KnowledgeTools(knowledge=knowledge, namespace="corpora/{tenant_id}")

    @pytest.mark.parametrize("namespace", ["corpora/static", "corpora/{user_id}", "corpora/{team_id}"])
    def test_v1_namespace_requires_exactly_agent_id(self, namespace):
        knowledge = Knowledge(name="K", vector_db=MemoryVectorDb(), contents_db=InMemoryDb())

        with pytest.raises(ValueError, match=r"exactly one \{agent_id\}"):
            KnowledgeTools(knowledge=knowledge, namespace=namespace)

    def test_namespaced_toolkit_rejects_unsupported_vector_database(self):
        vector_db = MemoryVectorDb()
        vector_db.supports_namespaced_knowledge = False
        knowledge = Knowledge(name="K", vector_db=vector_db, contents_db=InMemoryDb())

        with pytest.raises(ValueError, match="PgVector is currently supported"):
            KnowledgeTools(knowledge=knowledge, namespace="corpora/{agent_id}")

    def test_static_toolkit_keeps_existing_sync_search_registration(self):
        toolkit = KnowledgeTools(
            knowledge=Knowledge(name="K", vector_db=MemoryVectorDb()),
            enable_think=False,
            enable_analyze=False,
        )

        assert "search_knowledge" in toolkit.functions
        assert "search_knowledge" not in toolkit.async_functions

    def test_legacy_positional_constructor_order_is_preserved(self):
        knowledge = Knowledge(name="K", vector_db=MemoryVectorDb())

        toolkit = KnowledgeTools(knowledge, False, True, False, "legacy instructions", False, False, None, False)

        assert toolkit.knowledge is knowledge
        assert set(toolkit.functions) == {"search_knowledge"}
        assert toolkit.instructions == "legacy instructions"
        assert toolkit.namespace is None

    def test_add_tool_requires_agent_namespace(self):
        knowledge = Knowledge(name="K", vector_db=MemoryVectorDb(), contents_db=InMemoryDb())

        with pytest.raises(ValueError, match="requires an agent namespace"):
            KnowledgeTools(knowledge=knowledge, enable_add=True)

    def test_runtime_parameters_are_hidden_from_tool_schemas(self, knowledge_stack):
        toolkit, _, _, _ = knowledge_stack

        for functions in (toolkit.functions, toolkit.async_functions):
            for name in ("search_knowledge", "add_text_to_knowledge"):
                function = functions[name]
                function.process_entrypoint()
                properties = function.parameters["properties"]
                assert "agent" not in properties
                assert "team" not in properties
                assert "run_context" not in properties
        assert set(toolkit.functions["search_knowledge"].parameters["properties"]) == {"query"}
        assert set(toolkit.functions["add_text_to_knowledge"].parameters["properties"]) == {
            "name",
            "text_content",
        }


class TestIsolation:
    def test_two_agents_share_one_store_without_sharing_corpora(self, knowledge_stack):
        toolkit, knowledge, vector_db, contents_db = knowledge_stack
        alpha = Agent(id="alpha", name="Alpha", telemetry=False)
        beta = Agent(id="beta", name="Beta", telemetry=False)

        assert toolkit.add_text_to_knowledge(_context(), "private", "alpha secret", agent=alpha).startswith("Added")
        assert toolkit.add_text_to_knowledge(_context(), "private", "beta secret", agent=beta).startswith("Added")

        assert "alpha secret" in toolkit.search_knowledge(_context(), "secret", agent=alpha)
        assert "beta secret" not in toolkit.search_knowledge(_context(), "secret", agent=alpha)
        assert "beta secret" in toolkit.search_knowledge(_context(), "secret", agent=beta)
        assert "alpha secret" not in toolkit.search_knowledge(_context(), "secret", agent=beta)
        assert knowledge.name == "Registry knowledge"
        assert len(vector_db.records) == 2
        assert {row["linked_to"] for row in contents_db._knowledge} == {"corpora/alpha", "corpora/beta"}

    def test_identical_content_has_distinct_ids_per_agent(self, knowledge_stack):
        toolkit, _, vector_db, contents_db = knowledge_stack
        alpha = Agent(id="alpha", name="Alpha", telemetry=False)
        beta = Agent(id="beta", name="Beta", telemetry=False)

        toolkit.add_text_to_knowledge(_context(), "same", "identical text", agent=alpha)
        toolkit.add_text_to_knowledge(_context(), "same", "identical text", agent=beta)

        assert len(contents_db._knowledge) == 2
        assert len({row["id"] for row in contents_db._knowledge}) == 2
        assert len(vector_db.records) == 2
        assert len({content_hash for content_hash, _ in vector_db.records}) == 2

    @pytest.mark.asyncio
    async def test_async_add_and_search_are_isolated(self, knowledge_stack):
        toolkit, _, _, _ = knowledge_stack
        alpha = Agent(id="alpha", name="Alpha", telemetry=False)
        beta = Agent(id="beta", name="Beta", telemetry=False)

        assert (await toolkit.aadd_text_to_knowledge(_context(), "async", "alpha async", agent=alpha)).startswith(
            "Added"
        )

        assert "alpha async" in await toolkit.asearch_knowledge(_context(), "async", agent=alpha)
        assert await toolkit.asearch_knowledge(_context(), "async", agent=beta) == "No documents found"


class TestQuotas:
    def test_invalid_utf8_fails_before_creating_content(self, knowledge_stack):
        toolkit, _, _, contents_db = knowledge_stack
        agent = Agent(id="alpha", telemetry=False)

        result = toolkit.add_text_to_knowledge(_context(), "invalid", "\ud800", agent=agent)

        assert result.startswith("Error adding text to knowledge:")
        assert "surrogates not allowed" in result
        assert contents_db._knowledge == []

    @pytest.mark.parametrize(
        ("name", "error"),
        [
            ("x" * 256, "limit 255 bytes"),
            ("line\nbreak", "control characters"),
        ],
    )
    def test_name_caps_fail_before_creating_content(self, knowledge_stack, name, error):
        toolkit, _, _, contents_db = knowledge_stack
        agent = Agent(id="alpha", telemetry=False)

        result = toolkit.add_text_to_knowledge(_context(), name, "text", agent=agent)

        assert error in result
        assert contents_db._knowledge == []

    @pytest.mark.parametrize("is_async", [False, True])
    @pytest.mark.asyncio
    async def test_partial_chunk_indexing_is_reported_and_cleaned(self, is_async):
        vector_db = PartialVectorDb()
        toolkit = KnowledgeTools(
            knowledge=Knowledge(name="K", vector_db=vector_db, contents_db=InMemoryDb()),
            namespace="corpora/{agent_id}",
            enable_think=False,
            enable_analyze=False,
            enable_add=True,
            max_content_bytes=6_000,
            max_namespace_bytes=6_000,
        )
        agent = Agent(id="alpha", telemetry=False)
        text_content = "x" * 6_000

        if is_async:
            result = await toolkit.aadd_text_to_knowledge(_context(), "partial", text_content, agent=agent)
        else:
            result = await asyncio.to_thread(
                toolkit.add_text_to_knowledge,
                _context(),
                "partial",
                text_content,
                agent=agent,
            )

        assert result == "Error adding text to knowledge: knowledge indexing did not produce a searchable vector"
        assert vector_db.records == []

    def test_failed_post_check_cleans_committed_vectors_and_reserves_quota(self):
        vector_db = VerificationFailVectorDb()
        toolkit = KnowledgeTools(
            knowledge=Knowledge(name="K", vector_db=vector_db, contents_db=InMemoryDb()),
            namespace="corpora/{agent_id}",
            enable_think=False,
            enable_analyze=False,
            enable_add=True,
            max_content_bytes=1,
            max_namespace_bytes=1,
        )
        agent = Agent(id="alpha", telemetry=False)

        failed = toolkit.add_text_to_knowledge(_context(), "item", "x", agent=agent)
        different_name = toolkit.add_text_to_knowledge(_context(), "other", "y", agent=agent)
        vector_db.fail_verification = False
        recovered = toolkit.add_text_to_knowledge(_context(), "item", "y", agent=agent)

        assert failed == "Error adding text to knowledge: knowledge indexing did not produce a searchable vector"
        assert vector_db.cleaned_content_ids
        assert len(vector_db.records) == 1
        assert "knowledge is full" in different_name
        assert recovered.startswith("Added 1 bytes")

    @pytest.mark.parametrize("is_async", [False, True])
    @pytest.mark.asyncio
    async def test_silent_indexing_failure_is_reported_and_allows_same_name_retry(self, is_async):
        vector_db = SilentFailVectorDb()
        toolkit = KnowledgeTools(
            knowledge=Knowledge(name="K", vector_db=vector_db, contents_db=InMemoryDb()),
            namespace="corpora/{agent_id}",
            enable_think=False,
            enable_analyze=False,
            enable_add=True,
            max_content_bytes=1,
            max_namespace_bytes=1,
        )
        agent = Agent(id="alpha", telemetry=False)

        if is_async:
            failed = await toolkit.aadd_text_to_knowledge(_context(), "failed", "x", agent=agent)
        else:
            failed = await asyncio.to_thread(toolkit.add_text_to_knowledge, _context(), "failed", "x", agent=agent)
        vector_db.fail = False
        if is_async:
            recovered = await toolkit.aadd_text_to_knowledge(_context(), "failed", "y", agent=agent)
        else:
            recovered = await asyncio.to_thread(toolkit.add_text_to_knowledge, _context(), "failed", "y", agent=agent)

        assert failed == "Error adding text to knowledge: knowledge indexing did not produce a searchable vector"
        assert recovered.startswith("Added 1 bytes")

    def test_failed_indexing_is_reported_and_allows_same_name_retry(self):
        vector_db = FailingVectorDb()
        toolkit = KnowledgeTools(
            knowledge=Knowledge(name="K", vector_db=vector_db, contents_db=InMemoryDb()),
            namespace="corpora/{agent_id}",
            enable_think=False,
            enable_analyze=False,
            enable_add=True,
            max_content_bytes=1,
            max_namespace_bytes=1,
        )
        agent = Agent(id="alpha", telemetry=False)

        failed = toolkit.add_text_to_knowledge(_context(), "failed", "x", agent=agent)
        failed_status = toolkit._resolved(_context(), agent, None).get_content_status(
            toolkit._text_content_id(toolkit._resolved(_context(), agent, None), "failed", "x", 1)
        )[0]
        vector_db.fail = False
        recovered = toolkit.add_text_to_knowledge(_context(), "failed", "y", agent=agent)

        assert (
            failed == "Error adding text to knowledge: knowledge indexing did not complete: Could not upsert embedding"
        )
        assert failed_status == ContentStatus.FAILED
        assert recovered.startswith("Added 1 bytes")

    @pytest.mark.asyncio
    async def test_async_failed_indexing_is_reported_and_allows_same_name_retry(self):
        vector_db = FailingVectorDb()
        toolkit = KnowledgeTools(
            knowledge=Knowledge(name="K", vector_db=vector_db, contents_db=InMemoryDb()),
            namespace="corpora/{agent_id}",
            enable_think=False,
            enable_analyze=False,
            enable_add=True,
            max_content_bytes=1,
            max_namespace_bytes=1,
        )
        agent = Agent(id="alpha", telemetry=False)

        failed = await toolkit.aadd_text_to_knowledge(_context(), "failed", "x", agent=agent)
        vector_db.fail = False
        recovered = await toolkit.aadd_text_to_knowledge(_context(), "failed", "y", agent=agent)

        assert (
            failed == "Error adding text to knowledge: knowledge indexing did not complete: Could not upsert embedding"
        )
        assert recovered.startswith("Added 1 bytes")

    def test_item_and_namespace_caps_use_utf8_bytes(self):
        toolkit = KnowledgeTools(
            knowledge=Knowledge(name="K", vector_db=MemoryVectorDb(), contents_db=InMemoryDb()),
            namespace="corpora/{agent_id}",
            enable_think=False,
            enable_analyze=False,
            enable_add=True,
            max_content_bytes=4,
            max_namespace_bytes=5,
        )
        agent = Agent(id="alpha", name="Alpha", telemetry=False)

        assert toolkit.add_text_to_knowledge(_context(), "unicode", "éé", agent=agent).startswith("Added 4 bytes")
        assert toolkit.add_text_to_knowledge(_context(), "last", "x", agent=agent).startswith("Added 1 bytes")
        assert "knowledge is full" in toolkit.add_text_to_knowledge(_context(), "overflow", "y", agent=agent)
        assert "limit 4 bytes per item" in toolkit.add_text_to_knowledge(_context(), "large", "abcde", agent=agent)

    def test_same_name_retry_and_overwrite_use_delta_accounting(self):
        toolkit = KnowledgeTools(
            knowledge=Knowledge(name="K", vector_db=MemoryVectorDb(), contents_db=InMemoryDb()),
            namespace="corpora/{agent_id}",
            enable_think=False,
            enable_analyze=False,
            enable_add=True,
            max_content_bytes=4,
            max_namespace_bytes=5,
        )
        agent = Agent(id="alpha", telemetry=False)

        first = toolkit.add_text_to_knowledge(_context(), "same", "éé", agent=agent)
        retry = toolkit.add_text_to_knowledge(_context(), "same", "éé", agent=agent)
        overwrite = toolkit.add_text_to_knowledge(_context(), "same", "abc", agent=agent)
        final = toolkit.add_text_to_knowledge(_context(), "other", "xy", agent=agent)

        assert first.startswith("Added 4 bytes")
        assert retry.startswith("Added 4 bytes")
        assert overwrite.startswith("Added 3 bytes")
        assert final.startswith("Added 2 bytes")
        contents = toolkit._resolved(_context(), agent, None).get_content()[0]
        assert len(contents) == 2
        assert sum(content.size or 0 for content in contents) == 5

    @pytest.mark.asyncio
    async def test_sync_and_async_writes_share_one_namespace_lock(self):
        toolkit = KnowledgeTools(
            knowledge=SlowKnowledge(name="K", vector_db=MemoryVectorDb(), contents_db=InMemoryDb()),
            namespace="corpora/{agent_id}",
            enable_think=False,
            enable_analyze=False,
            enable_add=True,
            max_content_bytes=1,
            max_namespace_bytes=1,
        )
        agent = Agent(id="alpha", telemetry=False)

        sync_result, async_result = await asyncio.gather(
            asyncio.to_thread(toolkit.add_text_to_knowledge, _context(), "sync", "x", agent=agent),
            toolkit.aadd_text_to_knowledge(_context(), "async", "y", agent=agent),
        )

        assert sum(result.startswith("Added") for result in (sync_result, async_result)) == 1
        assert sum("knowledge is full" in result for result in (sync_result, async_result)) == 1
        contents, _ = toolkit._resolved(_context(), agent, None).get_content()
        assert sum(content.size or 0 for content in contents) == 1


class TestStudioPersistence:
    def test_two_studio_agents_rehydrate_one_namespaced_toolkit(self, tmp_path, knowledge_stack):
        toolkit, knowledge, _, _ = knowledge_stack
        component_db = SqliteDb(id="studio-db", db_file=str(tmp_path / "studio.db"))
        registry = Registry(
            tools=[toolkit],
            models=[OpenAIResponses(id="gpt-5.4")],
            dbs=[component_db],
        )
        studio = StudioTools(registry=registry, db=component_db)

        for name in ("Alpha", "Beta"):
            result = studio.create_agent(
                name=name,
                instructions="Use your private knowledge.",
                model_id="gpt-5.4",
                tool_names=["agent_knowledge"],
            )
            assert '"status": "created"' in result

        for agent_id, text in (("alpha", "alpha studio"), ("beta", "beta studio")):
            config = component_db.get_config(agent_id)["config"]
            assert {tool["toolkit"] for tool in config["tools"]} == {"agent_knowledge"}
            agent = Agent.from_dict(config, registry=registry)
            assert agent.id == agent_id
            run_context = _context()
            prepared_tools = determine_tools_for_model(
                agent=agent,
                model=agent.model,
                processed_tools=agent.tools or [],
                run_response=RunOutput(run_id=run_context.run_id, agent_id=agent.id),
                run_context=run_context,
                session=AgentSession(session_id=run_context.session_id or "session-1", agent_id=agent.id),
            )
            add_function = next(
                tool for tool in prepared_tools if isinstance(tool, Function) and tool.name == "add_text_to_knowledge"
            )
            assert add_function._agent is agent
            assert add_function._run_context is run_context
            result = FunctionCall(
                function=add_function,
                arguments={"name": "studio", "text_content": text},
            ).execute()
            assert result.status == "success"
            assert isinstance(result.result, str) and result.result.startswith("Added")

        assert "alpha studio" in toolkit.search_knowledge(
            _context(), "studio", agent=Agent(id="alpha", telemetry=False)
        )
        assert "beta studio" not in toolkit.search_knowledge(
            _context(), "studio", agent=Agent(id="alpha", telemetry=False)
        )
        assert "beta studio" in toolkit.search_knowledge(_context(), "studio", agent=Agent(id="beta", telemetry=False))
        assert knowledge.name == "Registry knowledge"
