"""Tests for KnowledgeCatalog."""

from typing import List, Tuple
from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.knowledge.content import Content, ContentStatus
from agno.knowledge.store.catalog import KnowledgeCatalog
from agno.knowledge.store.content_store import ContentStore


def _make_content(name: str, description: str = "", file_type: str = "", status: str = "completed") -> Content:
    return Content(
        id=f"id-{name}",
        name=name,
        description=description,
        file_type=file_type,
        status=ContentStatus(status) if status else None,
    )


class TestBuildCatalogContext:
    def test_empty_catalog(self):
        catalog = KnowledgeCatalog(content_store=None)
        assert catalog.build_catalog_context() == ""

    def test_catalog_with_documents(self):
        store = MagicMock(spec=ContentStore)
        store.contents_db = MagicMock()
        store.get_content = MagicMock(
            return_value=(
                [
                    _make_content("report.pdf", "Quarterly earnings report", ".pdf"),
                    _make_content("manual.txt", "Product manual", ".txt"),
                ],
                2,
            )
        )

        catalog = KnowledgeCatalog(content_store=store)
        context = catalog.build_catalog_context()

        assert "report.pdf" in context
        assert "Quarterly earnings report" in context
        assert "manual.txt" in context
        assert "Product manual" in context
        assert "1." in context
        assert "2." in context

    def test_catalog_with_no_descriptions(self):
        store = MagicMock(spec=ContentStore)
        store.contents_db = MagicMock()
        store.get_content = MagicMock(
            return_value=(
                [_make_content("data.csv", file_type=".csv")],
                1,
            )
        )

        catalog = KnowledgeCatalog(content_store=store)
        context = catalog.build_catalog_context()

        assert "data.csv" in context
        assert "(.csv)" in context

    @pytest.mark.asyncio
    async def test_async_catalog(self):
        store = MagicMock(spec=ContentStore)
        store.contents_db = MagicMock()
        store.aget_content = AsyncMock(
            return_value=(
                [_make_content("notes.md", "Meeting notes")],
                1,
            )
        )

        catalog = KnowledgeCatalog(content_store=store)
        context = await catalog.abuild_catalog_context()

        assert "notes.md" in context
        assert "Meeting notes" in context


class TestGetTools:
    def test_get_tools_returns_list_documents(self):
        store = MagicMock(spec=ContentStore)
        store.contents_db = MagicMock()
        store.get_content = MagicMock(return_value=([], 0))

        catalog = KnowledgeCatalog(content_store=store)
        tools = catalog.get_tools()

        assert len(tools) == 1
        assert tools[0].name == "list_documents"

    def test_list_documents_tool_works(self):
        store = MagicMock(spec=ContentStore)
        store.contents_db = MagicMock()
        store.get_content = MagicMock(
            return_value=(
                [_make_content("doc1.pdf", "A document")],
                1,
            )
        )

        catalog = KnowledgeCatalog(content_store=store)
        tools = catalog.get_tools()
        result = tools[0].entrypoint()

        assert "doc1.pdf" in result
        assert "A document" in result

    def test_list_documents_empty(self):
        store = MagicMock(spec=ContentStore)
        store.contents_db = MagicMock()
        store.get_content = MagicMock(return_value=([], 0))

        catalog = KnowledgeCatalog(content_store=store)
        tools = catalog.get_tools()
        result = tools[0].entrypoint()

        assert "No documents found" in result
