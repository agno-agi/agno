from pathlib import Path
from typing import AsyncIterator, Iterator, List, Union

from agno.document import Document
from agno.document.reader.docx_reader import DocxReader
from agno.knowledge.agent import AgentKnowledge


class DocxKnowledgeBase(AgentKnowledge):
    path: Union[str, Path]
    formats: List[str] = [".doc", ".docx"]
    reader: DocxReader = DocxReader()

    @property
    def document_lists(self) -> Iterator[List[Document]]:
        """Iterate over doc/docx files and yield lists of documents.
        Each object yielded by the iterator is a list of documents.

        Returns:
            Iterator[List[Document]]: Iterator yielding list of documents
        """
        _file_path: Path = Path(self.path) if isinstance(self.path, str) else self.path

        if _file_path.exists() and _file_path.is_dir():
            for _file in _file_path.glob("**/*"):
                if _file.suffix in self.formats:
                    yield self.reader.read(file=_file)
        elif _file_path.exists() and _file_path.is_file() and _file_path.suffix in self.formats:
            yield self.reader.read(file=_file_path)

    @property
    async def async_document_lists(self) -> AsyncIterator[List[Document]]:
        """Async version of document_lists.

        Returns:
            AsyncIterator[List[Document]]: Async iterator yielding list of documents
        """
        _file_path: Path = Path(self.path) if isinstance(self.path, str) else self.path

        if _file_path.exists() and _file_path.is_dir():
            for _file in _file_path.glob("**/*"):
                if _file.suffix in self.formats:
                    docs = await self.reader.async_read(file=_file)
                    if docs:
                        yield docs
        elif _file_path.exists() and _file_path.is_file() and _file_path.suffix in self.formats:
            docs = await self.reader.async_read(file=_file_path)
            if docs:
                yield docs
