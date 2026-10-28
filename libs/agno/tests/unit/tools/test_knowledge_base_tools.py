"""Unit tests for KnowledgeBaseTools: OS-wide knowledge management by knowledge id.

Runs against real Knowledge instances with SQLite contents dbs and the local stub vector
db from the KnowledgeManagementTools tests - no network: URL loads go through a fake reader.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from typing import Any, List, Optional

import pytest

from agno.db.sqlite import SqliteDb
from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.base import Reader
from agno.knowledge.types import ContentType
from agno.media import File
from agno.run import RunContext
from agno.tools.knowledge import KnowledgeBaseTools
from agno.tools.knowledge.bases import knowledge_base_id
from agno.utils.live_sequence import LiveSequence
from tests.unit.tools.test_knowledge_management_tools import StubVectorDb


class PageReader(Reader):
    """Fake URL reader: one document, no network."""

    @classmethod
    def get_supported_content_types(cls) -> List[ContentType]:
        return [ContentType.URL]

    def read(self, obj: Any, name: Optional[str] = None, password: Optional[str] = None) -> List[Document]:
        return [Document(content="page text", meta_data={"url": str(obj)})]

    async def async_read(self, obj: Any, name: Optional[str] = None, password: Optional[str] = None) -> List[Document]:
        return self.read(obj, name=name, password=password)


class FailingReader(PageReader):
    def read(self, obj: Any, name: Optional[str] = None, password: Optional[str] = None) -> List[Document]:
        raise RuntimeError("site unreachable")


def _kb(name: str, **kwargs: Any) -> Knowledge:
    db_file = os.path.join(tempfile.mkdtemp(), "contents.db")
    return Knowledge(name=name, vector_db=StubVectorDb(), contents_db=SqliteDb(db_file=db_file), **kwargs)


def _ctx(user_id: Optional[str] = "alice") -> RunContext:
    return RunContext(run_id="r1", session_id="s1", user_id=user_id)


def _call(toolkit: KnowledgeBaseTools, tool: str, use_async: bool, **kwargs: Any) -> dict:
    if use_async:
        return json.loads(asyncio.run(getattr(toolkit, "a" + tool)(**kwargs)))
    return json.loads(getattr(toolkit, tool)(**kwargs))


def test_registration_and_confirmation_gate():
    toolkit = KnowledgeBaseTools(knowledge=[_kb("docs")])
    expected = [
        "list_knowledge_bases",
        "list_content",
        "get_content",
        "search_knowledge",
        "add_url",
        "add_text",
        "add_files",
        "remove_content",
    ]
    assert list(toolkit.functions) == expected
    assert list(toolkit.async_functions) == expected
    assert toolkit.functions["remove_content"].requires_confirmation is True

    read_only = KnowledgeBaseTools(knowledge=[], add_content=False, remove_content=False)
    assert list(read_only.functions) == expected[:4]


def test_lists_bases_with_os_ids_and_follows_a_live_list():
    bases: List[Knowledge] = []
    toolkit = KnowledgeBaseTools(knowledge=LiveSequence(lambda: bases))
    assert json.loads(toolkit.list_knowledge_bases())["count"] == 0

    docs = _kb("docs", description="Product docs")
    bases.append(docs)
    listed = json.loads(toolkit.list_knowledge_bases())["knowledge_bases"]
    assert listed == [
        {"id": knowledge_base_id(docs), "name": "docs", "description": "Product docs", "remote": False, "readers": []}
    ]


@pytest.mark.parametrize("use_async", [False, True])
def test_add_text_then_get_list_and_remove_by_id_or_name(use_async):
    docs = _kb("docs")
    toolkit = KnowledgeBaseTools(knowledge=[_kb("other"), docs])

    added = _call(toolkit, "add_text", use_async, knowledge="docs", name="faq", text="Refunds take 5 days.")
    assert added["status"] == "added" and added["knowledge_id"] == knowledge_base_id(docs)
    content_id = added["content"]["id"]
    assert added["content"]["status"] == "completed"

    kb_id = knowledge_base_id(docs)
    got = _call(toolkit, "get_content", use_async, knowledge=kb_id, content_id=content_id)
    assert got["name"] == "faq"
    listed = _call(toolkit, "list_content", use_async, knowledge=kb_id)
    assert [row["id"] for row in listed["content"]] == [content_id] and listed["total"] == 1

    removed = _call(toolkit, "remove_content", use_async, knowledge="docs", content_id=content_id)
    assert removed == {"status": "removed", "id": content_id, "name": "faq"}
    assert "error" in _call(toolkit, "get_content", use_async, knowledge="docs", content_id=content_id)


@pytest.mark.parametrize("use_async", [False, True])
def test_add_url_uses_the_requested_reader_and_reports_failures(use_async):
    docs = _kb("docs", readers={"page": PageReader(), "broken": FailingReader()})
    toolkit = KnowledgeBaseTools(knowledge=[docs])

    added = _call(toolkit, "add_url", use_async, knowledge="docs", url="https://example.com/a", reader_id="page")
    assert added["status"] == "added" and added["reader"] == "PageReader"
    assert added["content"]["name"] == "https://example.com/a"

    failed = _call(toolkit, "add_url", use_async, knowledge="docs", url="https://example.com/b", reader_id="broken")
    assert "site unreachable" in failed["error"] and failed["content"]["status"] == "failed"

    missing = _call(toolkit, "add_url", use_async, knowledge="docs", url="https://example.com/c", reader_id="nope")
    assert missing["error"] == "Reader not found: nope" and missing["available"] == ["broken", "page"]


def test_llms_txt_urls_get_the_llms_txt_reader():
    from agno.knowledge.reader.llms_txt_reader import LLMsTxtReader

    docs = _kb("docs")
    reader, err = KnowledgeBaseTools._resolve_reader(docs, None, "https://docs.agno.com/llms.txt")
    assert err is None and isinstance(reader, LLMsTxtReader)
    for url in ("https://docs.agno.com/llms-full.txt", "https://docs.agno.com/intro"):
        assert KnowledgeBaseTools._resolve_reader(docs, None, url) == (None, None)

    # A reader the base declares wins over a fresh factory one.
    configured = LLMsTxtReader(max_urls=5)
    reader, _ = KnowledgeBaseTools._resolve_reader(
        _kb("x", readers={"llms": configured}), None, "https://a.io/llms.txt"
    )
    assert reader is configured


def test_unknown_and_ambiguous_references_are_errors():
    toolkit = KnowledgeBaseTools(knowledge=[_kb("docs")])
    missing = json.loads(toolkit.list_content(knowledge="nope"))
    assert missing["error"] == "Knowledge base not found: nope" and missing["available"][0]["name"] == "docs"
    assert "error" in json.loads(toolkit.add_text(knowledge="docs", name=" ", text="x"))


def test_user_isolation_scopes_writes_and_refuses_shared_removal():
    docs = _kb("docs")
    isolated = {"on": False}
    toolkit = KnowledgeBaseTools(knowledge=[docs], user_isolation=lambda: isolated["on"])

    shared = json.loads(toolkit.add_text(knowledge="docs", name="shared", text="for all", run_context=_ctx()))
    assert docs.get_content_by_id(shared["content"]["id"]).user_id is None

    isolated["on"] = True
    own = json.loads(toolkit.add_text(knowledge="docs", name="mine", text="for alice", run_context=_ctx()))
    assert docs.get_content_by_id(own["content"]["id"]).user_id == "alice"

    refused = json.loads(
        toolkit.remove_content(knowledge="docs", content_id=shared["content"]["id"], run_context=_ctx())
    )
    assert refused["error"] == "Shared content can only be removed by an admin"
    assert "error" in json.loads(toolkit.list_content(knowledge="docs", run_context=_ctx(None)))


def _attached(name: str, data: bytes = b"Quarterly numbers.", mime: str = "text/plain") -> File:
    return File(content=data, filename=name, mime_type=mime)


@pytest.mark.parametrize("use_async", [False, True])
def test_add_files_loads_attachments_and_reports_each_one(use_async):
    docs = _kb("docs")
    toolkit = KnowledgeBaseTools(knowledge=[docs])
    files = [_attached("notes.txt"), _attached("guide.md", b"# Guide", "text/markdown"), _attached("bundle.zip")]

    result = _call(toolkit, "add_files", use_async, knowledge="docs", files=files, metadata={"source": "chat"})
    assert result["status"] == "partial" and result["loaded"] == 2
    by_name = {row["filename"]: row for row in result["files"]}
    assert by_name["notes.txt"]["content"]["status"] == "completed"
    assert by_name["guide.md"]["content"]["metadata"] == {"source": "chat"}
    assert by_name["bundle.zip"]["error"] == "Unsupported file type: .zip"
    stored = sorted(row.name for row in docs.get_content()[0])
    assert stored == ["guide.md", "notes.txt"]


@pytest.mark.parametrize("use_async", [False, True])
def test_add_files_picks_named_files_and_needs_attachments(use_async):
    toolkit = KnowledgeBaseTools(knowledge=[_kb("docs")])
    files = [_attached("a.txt"), _attached("b.txt", b"other")]

    picked = _call(toolkit, "add_files", use_async, knowledge="docs", files=files, filenames=["b.txt", "c.pdf"])
    assert [row["filename"] for row in picked["files"]] == ["b.txt", "c.pdf"]
    assert picked["files"][1]["error"] == "Not attached to this message" and picked["status"] == "partial"

    none = _call(toolkit, "add_files", use_async, knowledge="docs")
    assert none["error"].startswith("No files are attached to this message")
    nothing = _call(toolkit, "add_files", use_async, knowledge="docs", files=files, filenames=["zzz.txt"])
    assert nothing["error"] == "No files were loaded" and nothing["loaded"] == 0


def test_add_files_takes_url_files_and_refuses_local_paths(tmp_path):
    docs = _kb("docs", readers={"page": PageReader()})
    toolkit = KnowledgeBaseTools(knowledge=[docs])
    secret = tmp_path / "secret.txt"
    secret.write_text("do not load")

    kb = toolkit._find("docs")[0]
    content, reader, reason = toolkit._file_content(kb, File(url="https://a.io/llms.txt"), None, None, None)
    assert reason is None and content.url == "https://a.io/llms.txt" and type(reader).__name__ == "LLMsTxtReader"

    refused = json.loads(toolkit.add_files(knowledge="docs", files=[File(filepath=str(secret))]))
    assert refused["files"][0]["error"] == "The file has no content to load"
    assert docs.get_content()[1] == 0


def test_add_files_receives_the_run_files_through_injection():
    from agno.tools.function import FunctionCall

    docs = _kb("docs")
    function = KnowledgeBaseTools(knowledge=[docs]).functions["add_files"]
    function.process_entrypoint()
    assert set(function.parameters["properties"]) == {"knowledge", "filenames", "description", "metadata"}

    function._files = [_attached("injected.txt")]
    call = FunctionCall(function=function, arguments={"knowledge": "docs"})
    call.execute()
    assert json.loads(call.result)["files"][0]["content"]["name"] == "injected.txt"
