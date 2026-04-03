"""Unit tests for PageIndexKnowledge implementation."""

import json
import shutil
from pathlib import Path

import pytest

from agno.knowledge.pageindex.config import PageIndexSettings
from agno.knowledge.pageindex.registry import DocumentRegistry, RegistryRecord
from agno.knowledge.pageindex.retrieval import (
    _rank_nodes,
    invalidate_structure_cache,
    retrieve,
    retrieve_multi,
)
from agno.knowledge.pageindex.schemas import RetrievalResult

# -- test data paths -----------------------------------------------------------

_DATA_DIR = Path(__file__).parent / "pageindex_data"
_SAMPLE_MD = _DATA_DIR / "sample.md"
_SAMPLE_STRUCTURE = _DATA_DIR / "sample_structure.json"


# -- fixtures ------------------------------------------------------------------


@pytest.fixture
def knowledge_dir(tmp_path):
    """Create a PageIndexKnowledge with a pre-registered document."""
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    tenant_dir = results_dir / "test"
    tenant_dir.mkdir()

    # Copy structure JSON into results dir
    dest_structure = tenant_dir / "sample_structure.json"
    shutil.copy(_SAMPLE_STRUCTURE, dest_structure)

    # Register the document
    registry = DocumentRegistry(base_dir=results_dir, tenant_id="test")
    record = RegistryRecord(
        doc_id="doc_tax",
        doc_name="Tax Policy Guide",
        doc_type="md",
        source_path=str(_SAMPLE_MD),
        structure_path=str(dest_structure),
        indexed_at=DocumentRegistry.now_iso(),
        content_hash="abc123",
    )
    registry.upsert(record)

    # Clear structure cache between tests
    invalidate_structure_cache()

    return {
        "results_dir": results_dir,
        "registry": registry,
        "record": record,
        "structure_path": dest_structure,
    }


@pytest.fixture
def settings(knowledge_dir):
    return PageIndexSettings(
        tenant_id="test",
        results_dir=knowledge_dir["results_dir"],
    )


# -- PageIndexSettings --------------------------------------------------------


def test_settings_defaults():
    settings = PageIndexSettings()
    assert settings.tenant_id == "default"
    assert settings.llm_provider == "openai"
    assert settings.top_k_nodes == 6
    assert settings.min_retrieval_score == 2
    assert settings.max_evidence_chars == 9000
    assert settings.active_model == "gpt-4o-2024-11-20"


def test_settings_ollama_provider():
    settings = PageIndexSettings(llm_provider="ollama")
    assert settings.active_model == "qwen2.5:7b"


def test_settings_model_override():
    settings = PageIndexSettings(model="custom-model")
    assert settings.active_model == "custom-model"


def test_settings_tenant_paths():
    settings = PageIndexSettings(
        results_dir=Path("/tmp/test_results"),
        tenant_id="acme",
    )
    assert settings.tenant_results_dir == Path("/tmp/test_results/acme")
    assert settings.registry_path == Path("/tmp/test_results/acme/doc_registry.json")


def test_settings_prepare_environment(tmp_path):
    settings = PageIndexSettings(
        results_dir=tmp_path / "results",
        upload_dir=tmp_path / "uploads",
        tenant_id="t1",
    )
    settings.prepare_environment()
    assert (tmp_path / "results" / "t1").is_dir()
    assert (tmp_path / "uploads" / "t1").is_dir()


# -- DocumentRegistry ---------------------------------------------------------


def test_registry_empty(tmp_path):
    registry = DocumentRegistry(base_dir=tmp_path, tenant_id="test")
    assert registry.count() == 0
    assert registry.list() == []
    assert registry.get("nonexistent") is None


def test_registry_upsert_and_get(tmp_path):
    registry = DocumentRegistry(base_dir=tmp_path, tenant_id="test")
    record = RegistryRecord(
        doc_id="doc_abc",
        doc_name="Test Doc",
        doc_type="pdf",
        source_path="/path/to/test.pdf",
        structure_path="/path/to/structure.json",
        indexed_at=DocumentRegistry.now_iso(),
        content_hash="abc123",
    )
    registry.upsert(record)
    assert registry.count() == 1
    retrieved = registry.get("doc_abc")
    assert retrieved is not None
    assert retrieved.doc_name == "Test Doc"
    assert retrieved.content_hash == "abc123"


def test_registry_delete(tmp_path):
    registry = DocumentRegistry(base_dir=tmp_path, tenant_id="test")
    record = RegistryRecord(
        doc_id="doc_del",
        doc_name="Delete Me",
        doc_type="md",
        source_path="/path",
        structure_path="/path",
        indexed_at=DocumentRegistry.now_iso(),
    )
    registry.upsert(record)
    assert registry.delete("doc_del")
    assert registry.count() == 0
    assert not registry.delete("doc_del")


def test_registry_find_by_hash(tmp_path):
    registry = DocumentRegistry(base_dir=tmp_path, tenant_id="test")
    record = RegistryRecord(
        doc_id="doc_hash",
        doc_name="Hashed",
        doc_type="pdf",
        source_path="/path",
        structure_path="/path",
        indexed_at=DocumentRegistry.now_iso(),
        content_hash="deadbeef",
    )
    registry.upsert(record)
    found = registry.find_by_hash("deadbeef")
    assert found is not None
    assert found.doc_id == "doc_hash"
    assert registry.find_by_hash("nonexistent") is None
    assert registry.find_by_hash("") is None


def test_registry_get_or_raise(tmp_path):
    registry = DocumentRegistry(base_dir=tmp_path, tenant_id="test")
    with pytest.raises(KeyError, match="Unknown doc_id"):
        registry.get_or_raise("nonexistent")


def test_registry_persistence(tmp_path):
    """Registry state should survive re-instantiation."""
    registry1 = DocumentRegistry(base_dir=tmp_path, tenant_id="test")
    record = RegistryRecord(
        doc_id="doc_persist",
        doc_name="Persistent",
        doc_type="pdf",
        source_path="/path",
        structure_path="/path",
        indexed_at=DocumentRegistry.now_iso(),
    )
    registry1.upsert(record)

    registry2 = DocumentRegistry(base_dir=tmp_path, tenant_id="test")
    assert registry2.count() == 1
    assert registry2.get("doc_persist") is not None


def test_registry_list_sorted_by_indexed_at(tmp_path):
    registry = DocumentRegistry(base_dir=tmp_path, tenant_id="test")
    registry.upsert(
        RegistryRecord(
            doc_id="old",
            doc_name="Old",
            doc_type="md",
            source_path="/p",
            structure_path="/s",
            indexed_at="2024-01-01T00:00:00Z",
        )
    )
    registry.upsert(
        RegistryRecord(
            doc_id="new",
            doc_name="New",
            doc_type="md",
            source_path="/p",
            structure_path="/s",
            indexed_at="2024-06-01T00:00:00Z",
        )
    )
    records = registry.list()
    assert records[0].doc_id == "new"
    assert records[1].doc_id == "old"


# -- Keyword ranking -----------------------------------------------------------


def _make_structure(nodes):
    return {"structure": nodes}


def test_rank_nodes_title_match():
    structure = _make_structure(
        [
            {
                "title": "Tax Policy",
                "summary": "Overview of taxation.",
                "start_index": 1,
                "end_index": 5,
                "node_id": "001",
            },
            {
                "title": "Revenue Report",
                "summary": "Annual revenue.",
                "start_index": 6,
                "end_index": 10,
                "node_id": "002",
            },
        ]
    )
    ranked = _rank_nodes("tax policy", structure, top_k=5)
    assert len(ranked) >= 1
    assert ranked[0].title == "Tax Policy"
    assert ranked[0].score > 0


def test_rank_nodes_summary_match():
    structure = _make_structure(
        [
            {
                "title": "Chapter 1",
                "summary": "Discussion of revenue forecasting.",
                "start_index": 1,
                "end_index": 5,
                "node_id": "001",
            },
        ]
    )
    ranked = _rank_nodes("revenue forecasting", structure, top_k=5)
    assert len(ranked) >= 1
    assert ranked[0].score > 0


def test_rank_nodes_no_match():
    structure = _make_structure(
        [
            {"title": "Introduction", "summary": "Welcome.", "start_index": 1, "end_index": 2, "node_id": "001"},
        ]
    )
    ranked = _rank_nodes("quantum physics", structure, top_k=5)
    assert len(ranked) == 0


def test_rank_nodes_nested():
    structure = _make_structure(
        [
            {
                "title": "Part 1",
                "summary": "Overview",
                "start_index": 1,
                "end_index": 20,
                "node_id": "001",
                "nodes": [
                    {
                        "title": "Tax Guidelines",
                        "summary": "Detailed tax rules.",
                        "start_index": 5,
                        "end_index": 10,
                        "node_id": "002",
                    },
                ],
            },
        ]
    )
    ranked = _rank_nodes("tax guidelines", structure, top_k=5)
    assert any(r.title == "Tax Guidelines" for r in ranked)


def test_rank_nodes_phrase_bonus():
    """Full query phrase match should give a +4 bonus."""
    structure = _make_structure(
        [
            {
                "title": "Sales Tax Rate",
                "summary": "Details on sales tax rate schedules.",
                "start_index": 1,
                "end_index": 5,
                "node_id": "001",
            },
        ]
    )
    ranked = _rank_nodes("sales tax rate", structure, top_k=5)
    assert len(ranked) == 1
    # title matches all 3 terms (3*3 = 9) + phrase bonus (4) = 13
    assert ranked[0].score >= 13


def test_rank_nodes_stop_words_filtered():
    """Stop words should not affect scoring."""
    structure = _make_structure(
        [
            {
                "title": "Tax Policy",
                "summary": "Overview.",
                "start_index": 1,
                "end_index": 5,
                "node_id": "001",
            },
        ]
    )
    # "the" and "of" are stop words, only "tax" and "policy" should be used
    ranked_with_stops = _rank_nodes("the tax policy of the year", structure, top_k=5)
    ranked_without_stops = _rank_nodes("tax policy", structure, top_k=5)
    assert len(ranked_with_stops) == 1
    assert len(ranked_without_stops) == 1
    # Scores should differ by the term coverage from "year" but titles match the same
    assert ranked_with_stops[0].title == ranked_without_stops[0].title


def test_rank_nodes_top_k_limit():
    nodes = [
        {
            "title": f"Tax Section {i}",
            "summary": f"Tax details {i}.",
            "start_index": i,
            "end_index": i,
            "node_id": str(i),
        }
        for i in range(20)
    ]
    structure = _make_structure(nodes)
    ranked = _rank_nodes("tax", structure, top_k=3)
    assert len(ranked) == 3


# -- Retrieval (full flow with Markdown) ----------------------------------------


def test_retrieve_single_doc(knowledge_dir, settings):
    """Test retrieve returns evidence from a markdown document."""
    record = knowledge_dir["record"]
    results = retrieve("income tax", record, settings, top_k=3)
    assert len(results) >= 1
    assert not results[0].insufficient_evidence
    assert results[0].score > 0
    # Should contain actual content from the markdown file
    assert len(results[0].content) > 0


def test_retrieve_no_match(knowledge_dir, settings):
    """No match returns insufficient evidence marker."""
    record = knowledge_dir["record"]
    results = retrieve("quantum entanglement", record, settings, top_k=3)
    assert len(results) == 1
    assert results[0].insufficient_evidence


def test_retrieve_multi_docs(knowledge_dir, settings):
    """Test multi-document retrieval."""
    records = knowledge_dir["registry"].list()
    results = retrieve_multi("corporate tax filing", records, settings, max_docs=3)
    assert len(results) >= 1
    has_real_result = any(not r.insufficient_evidence for r in results)
    assert has_real_result


def test_retrieve_multi_no_docs(settings):
    """Empty registry returns insufficient evidence."""
    results = retrieve_multi("anything", [], settings)
    assert len(results) == 1
    assert results[0].insufficient_evidence


def test_retrieve_term_coverage(knowledge_dir, settings):
    """Term coverage should be between 0 and 1."""
    record = knowledge_dir["record"]
    results = retrieve("tax brackets deductions", record, settings)
    for r in results:
        if not r.insufficient_evidence:
            assert 0.0 <= r.term_coverage <= 1.0


# -- RetrievalResult schema ----------------------------------------------------


def test_retrieval_result_defaults():
    result = RetrievalResult(content="test")
    assert result.score == 0
    assert result.insufficient_evidence is False
    assert result.doc_id == ""


# -- PageIndexKnowledge (full integration) --------------------------------------


def test_import_pageindex_knowledge():
    """Verify the public import path works."""
    from agno.knowledge.pageindex import PageIndexKnowledge

    assert PageIndexKnowledge is not None


def test_knowledge_initialization(tmp_path):
    """PageIndexKnowledge creates dirs on init."""
    from agno.knowledge.pageindex import PageIndexKnowledge

    knowledge = PageIndexKnowledge(
        results_dir=str(tmp_path / "results"),
        upload_dir=str(tmp_path / "uploads"),
        tenant_id="init_test",
    )
    assert (tmp_path / "results" / "init_test").is_dir()
    assert (tmp_path / "uploads" / "init_test").is_dir()
    assert knowledge.registry.count() == 0


def test_knowledge_build_context(knowledge_dir):
    """build_context should mention indexed documents."""
    from agno.knowledge.pageindex import PageIndexKnowledge

    knowledge = PageIndexKnowledge(
        results_dir=str(knowledge_dir["results_dir"]),
        tenant_id="test",
    )
    context = knowledge.build_context()
    assert "PageIndex" in context
    assert "Tax Policy Guide" in context
    assert "doc_tax" in context


def test_knowledge_build_context_empty(tmp_path):
    """build_context with no documents should say 'none yet'."""
    from agno.knowledge.pageindex import PageIndexKnowledge

    knowledge = PageIndexKnowledge(
        results_dir=str(tmp_path / "results"),
        tenant_id="empty_test",
    )
    context = knowledge.build_context()
    assert "none yet" in context


def test_knowledge_get_tools(knowledge_dir):
    """get_tools should return 3 Function tools."""
    from agno.knowledge.pageindex import PageIndexKnowledge
    from agno.tools.function import Function

    knowledge = PageIndexKnowledge(
        results_dir=str(knowledge_dir["results_dir"]),
        tenant_id="test",
    )
    tools = knowledge.get_tools()
    assert len(tools) == 3
    assert all(isinstance(t, Function) for t in tools)
    tool_names = {t.name for t in tools}
    assert tool_names == {"search_documents", "list_documents", "get_document_structure"}


def test_knowledge_list_documents(knowledge_dir):
    """list_indexed_documents should return registered docs."""
    from agno.knowledge.pageindex import PageIndexKnowledge

    knowledge = PageIndexKnowledge(
        results_dir=str(knowledge_dir["results_dir"]),
        tenant_id="test",
    )
    docs = knowledge.list_indexed_documents()
    assert len(docs) == 1
    assert docs[0].doc_id == "doc_tax"
    assert docs[0].doc_name == "Tax Policy Guide"


def test_knowledge_get_document(knowledge_dir):
    """get_document should return metadata for a specific doc."""
    from agno.knowledge.pageindex import PageIndexKnowledge

    knowledge = PageIndexKnowledge(
        results_dir=str(knowledge_dir["results_dir"]),
        tenant_id="test",
    )
    doc = knowledge.get_document("doc_tax")
    assert doc is not None
    assert doc.doc_type == "md"
    assert knowledge.get_document("nonexistent") is None


def test_knowledge_get_structure(knowledge_dir):
    """get_structure should return the hierarchical JSON."""
    from agno.knowledge.pageindex import PageIndexKnowledge

    knowledge = PageIndexKnowledge(
        results_dir=str(knowledge_dir["results_dir"]),
        tenant_id="test",
    )
    structure = knowledge.get_structure("doc_tax")
    assert structure is not None
    assert "structure" in structure
    assert len(structure["structure"]) == 4  # Overview, Income Tax, Corporate Tax, Sales Tax
    assert knowledge.get_structure("nonexistent") is None


def test_knowledge_delete_document(knowledge_dir):
    """delete_document should remove from registry."""
    from agno.knowledge.pageindex import PageIndexKnowledge

    knowledge = PageIndexKnowledge(
        results_dir=str(knowledge_dir["results_dir"]),
        tenant_id="test",
    )
    assert knowledge.delete_document("doc_tax")
    assert knowledge.registry.count() == 0
    assert not knowledge.delete_document("doc_tax")


def test_knowledge_retrieve(knowledge_dir):
    """retrieve should return Document objects for context injection."""
    from agno.knowledge.pageindex import PageIndexKnowledge

    invalidate_structure_cache()
    knowledge = PageIndexKnowledge(
        results_dir=str(knowledge_dir["results_dir"]),
        tenant_id="test",
    )
    docs = knowledge.retrieve("corporate tax")
    assert len(docs) >= 1
    assert docs[0].content
    assert docs[0].meta_data.get("score", 0) > 0


def test_knowledge_retrieve_empty(tmp_path):
    """retrieve with no documents returns empty list."""
    from agno.knowledge.pageindex import PageIndexKnowledge

    knowledge = PageIndexKnowledge(
        results_dir=str(tmp_path / "results"),
        tenant_id="empty_test",
    )
    docs = knowledge.retrieve("anything")
    assert docs == []


def test_knowledge_search_tool(knowledge_dir):
    """search_documents tool should return formatted results."""
    from agno.knowledge.pageindex import PageIndexKnowledge

    invalidate_structure_cache()
    knowledge = PageIndexKnowledge(
        results_dir=str(knowledge_dir["results_dir"]),
        tenant_id="test",
    )
    tools = knowledge.get_tools()
    search_tool = next(t for t in tools if t.name == "search_documents")
    result = search_tool.entrypoint(query="income tax brackets")
    assert "Tax Brackets" in result or "Income Tax" in result
    assert "Score:" in result


def test_knowledge_search_tool_no_match(knowledge_dir):
    """search_documents with no match returns appropriate message."""
    from agno.knowledge.pageindex import PageIndexKnowledge

    invalidate_structure_cache()
    knowledge = PageIndexKnowledge(
        results_dir=str(knowledge_dir["results_dir"]),
        tenant_id="test",
    )
    tools = knowledge.get_tools()
    search_tool = next(t for t in tools if t.name == "search_documents")
    result = search_tool.entrypoint(query="quantum entanglement")
    assert "No relevant sections" in result


def test_knowledge_search_tool_by_doc_id(knowledge_dir):
    """search_documents can filter by doc_id."""
    from agno.knowledge.pageindex import PageIndexKnowledge

    invalidate_structure_cache()
    knowledge = PageIndexKnowledge(
        results_dir=str(knowledge_dir["results_dir"]),
        tenant_id="test",
    )
    tools = knowledge.get_tools()
    search_tool = next(t for t in tools if t.name == "search_documents")

    result = search_tool.entrypoint(query="corporate tax", doc_id="doc_tax")
    assert "Corporate Tax" in result

    result_bad_id = search_tool.entrypoint(query="corporate tax", doc_id="nonexistent")
    assert "not found" in result_bad_id.lower()


def test_knowledge_list_tool(knowledge_dir):
    """list_documents tool should show registered documents."""
    from agno.knowledge.pageindex import PageIndexKnowledge

    knowledge = PageIndexKnowledge(
        results_dir=str(knowledge_dir["results_dir"]),
        tenant_id="test",
    )
    tools = knowledge.get_tools()
    list_tool = next(t for t in tools if t.name == "list_documents")
    result = list_tool.entrypoint()
    assert "Tax Policy Guide" in result
    assert "doc_tax" in result


def test_knowledge_structure_tool(knowledge_dir):
    """get_document_structure tool should return JSON."""
    from agno.knowledge.pageindex import PageIndexKnowledge

    knowledge = PageIndexKnowledge(
        results_dir=str(knowledge_dir["results_dir"]),
        tenant_id="test",
    )
    tools = knowledge.get_tools()
    structure_tool = next(t for t in tools if t.name == "get_document_structure")
    result = structure_tool.entrypoint(doc_id="doc_tax")
    parsed = json.loads(result)
    assert "structure" in parsed

    result_bad = structure_tool.entrypoint(doc_id="nonexistent")
    assert "not found" in result_bad.lower() or "unavailable" in result_bad.lower()


# -- Async variants ------------------------------------------------------------


@pytest.mark.asyncio
async def test_knowledge_aretrieve(knowledge_dir):
    """aretrieve should return the same results as retrieve."""
    from agno.knowledge.pageindex import PageIndexKnowledge

    invalidate_structure_cache()
    knowledge = PageIndexKnowledge(
        results_dir=str(knowledge_dir["results_dir"]),
        tenant_id="test",
    )
    sync_docs = knowledge.retrieve("sales tax")
    async_docs = await knowledge.aretrieve("sales tax")
    assert len(async_docs) == len(sync_docs)
    if async_docs:
        assert async_docs[0].content == sync_docs[0].content


@pytest.mark.asyncio
async def test_knowledge_aget_tools(knowledge_dir):
    """aget_tools should return the same tools as get_tools."""
    from agno.knowledge.pageindex import PageIndexKnowledge

    knowledge = PageIndexKnowledge(
        results_dir=str(knowledge_dir["results_dir"]),
        tenant_id="test",
    )
    sync_tools = knowledge.get_tools()
    async_tools = await knowledge.aget_tools()
    assert len(async_tools) == len(sync_tools)
    assert {t.name for t in async_tools} == {t.name for t in sync_tools}


# -- Indexing helpers -----------------------------------------------------------


def test_detect_doc_type():
    from agno.knowledge.pageindex.indexing import _detect_doc_type

    assert _detect_doc_type(Path("report.pdf")) == "pdf"
    assert _detect_doc_type(Path("notes.md")) == "md"
    assert _detect_doc_type(Path("notes.markdown")) == "md"
    with pytest.raises(ValueError, match="Unsupported"):
        _detect_doc_type(Path("data.csv"))


def test_build_doc_id():
    from agno.knowledge.pageindex.indexing import _build_doc_id

    id1 = _build_doc_id(Path("/a/b.pdf"), "t1")
    id2 = _build_doc_id(Path("/a/b.pdf"), "t2")
    assert id1 != id2  # Different tenants produce different IDs
    assert id1.startswith("doc_")
    assert len(id1) == 16  # "doc_" + 12 hex chars


def test_file_hash(tmp_path):
    from agno.knowledge.pageindex.indexing import _file_hash

    f = tmp_path / "test.txt"
    f.write_text("hello world")
    h = _file_hash(f)
    assert len(h) == 64  # SHA-256 hex


def test_list_candidate_files(tmp_path):
    from agno.knowledge.pageindex.indexing import list_candidate_files

    (tmp_path / "a.pdf").write_text("pdf")
    (tmp_path / "b.pdf").write_text("pdf")
    (tmp_path / "c.txt").write_text("txt")
    files = list_candidate_files(str(tmp_path), "*.pdf")
    assert len(files) == 2

    with pytest.raises(NotADirectoryError):
        list_candidate_files("/nonexistent/path/12345", "*.pdf")


# -- Structure cache -----------------------------------------------------------


def test_structure_cache_invalidation(knowledge_dir):
    """Cache invalidation should force re-read from disk."""
    record = knowledge_dir["record"]
    settings = PageIndexSettings(tenant_id="test", results_dir=knowledge_dir["results_dir"])

    invalidate_structure_cache()
    # Populate the cache by performing a retrieval
    retrieve("income tax", record, settings)

    # Modify structure on disk
    with Path(record.structure_path).open("r") as f:
        data = json.load(f)
    data["structure"][0]["title"] = "Modified Title"
    with Path(record.structure_path).open("w") as f:
        json.dump(data, f)

    # Without invalidation, cache still returns old data
    retrieve("modified title", record, settings)
    # After invalidation, should pick up changes
    invalidate_structure_cache(record.structure_path)
    results_fresh = retrieve("modified title", record, settings)

    # The fresh results should find the modified title
    has_modified = any(r.title == "Modified Title" for r in results_fresh if not r.insufficient_evidence)
    assert has_modified
