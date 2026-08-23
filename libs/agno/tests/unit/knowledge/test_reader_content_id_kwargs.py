"""Knowledge only passes content_id when the reader signature accepts it."""

from typing import Any, List, Optional

from agno.knowledge.content import Content
from agno.knowledge.document.base import Document
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.base import Reader


class LegacyReader(Reader):
    """Old-style reader without content_id / password parameters."""

    def read(self, obj: Any, name: Optional[str] = None) -> List[Document]:
        return [Document(name=name or "legacy", content=str(obj))]

    async def async_read(self, obj: Any, name: Optional[str] = None) -> List[Document]:
        return self.read(obj, name=name)


class ModernReader(Reader):
    def read(
        self,
        obj: Any,
        name: Optional[str] = None,
        content_id: Optional[str] = None,
    ) -> List[Document]:
        return [Document(name=name or "modern", content=f"{obj}:{content_id}")]

    async def async_read(
        self,
        obj: Any,
        name: Optional[str] = None,
        content_id: Optional[str] = None,
    ) -> List[Document]:
        return self.read(obj, name=name, content_id=content_id)


def test_read_works_with_legacy_reader_signature():
    knowledge = Knowledge()
    content = Content(id="cid-1", name="n")
    docs = knowledge._read(LegacyReader(chunk=False), "hello", name="doc", content=content)
    assert len(docs) == 1
    assert docs[0].content == "hello"


def test_read_passes_content_id_to_modern_reader():
    knowledge = Knowledge()
    content = Content(id="cid-1", name="n")
    docs = knowledge._read(ModernReader(chunk=False), "hello", name="doc", content=content)
    assert docs[0].content == "hello:cid-1"
