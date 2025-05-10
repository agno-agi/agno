import asyncio
from pathlib import Path
from typing import AsyncIterator, Iterator, List, Union

from agno.document import Document
from agno.document.reader.json_reader import JSONReader
from agno.knowledge.agent import AgentKnowledge


class JSONKnowledgeBase(AgentKnowledge):
    path: Union[str, Path]
    reader: JSONReader = JSONReader()

    @property
    def document_lists(self) -> Iterator[List[Document]]:
        """Iterate over Json files and yield lists of documents.
        Each object yielded by the iterator is a list of documents.

        Returns:
            Iterator[List[Document]]: Iterator yielding list of documents
        """
        _json_path: Path = Path(self.path) if isinstance(self.path, str) else self.path

        if _json_path.exists() and _json_path.is_dir():
            for _json in _json_path.glob("*.json"):
                yield self.reader.read(path=_json)
        elif _json_path.exists() and _json_path.is_file() and _json_path.suffix == ".json":
            yield self.reader.read(path=_json_path)

    @property
    async def async_document_lists(self) -> AsyncIterator[List[Document]]:
        """Asynchronously iterate over Json files and yield lists of documents.
        Each object yielded by the iterator is a list of documents.

        Returns:
            AsyncIterator[List[Document]]: Async iterator yielding list of documents
        """
        _json_path: Path = Path(self.path) if isinstance(self.path, str) else self.path

        if _json_path.exists() and _json_path.is_dir():
            json_files = list(_json_path.glob("*.json"))

            tasks = [self.reader.async_read(path=json_file) for json_file in json_files]
            if tasks:
                results = await asyncio.gather(*tasks)
                for result in results:
                    yield result

        elif _json_path.exists() and _json_path.is_file() and _json_path.suffix == ".json":
            result = await self.reader.async_read(path=_json_path)
            yield result
