from typing import Iterator, List

from agno.document import Document
from agno.document.reader.arxiv_reader import ArxivReader
from agno.knowledge.agent import AgentKnowledge


class ArxivKnowledgeBase(AgentKnowledge):
    queries: List[str] = []
    reader: ArxivReader = ArxivReader()

    @property
    def document_lists(self) -> Iterator[List[Document]]:
        """Iterate over urls and yield lists of documents.
        Each object yielded by the iterator is a list of documents.

        Returns:
            Iterator[List[Document]]: Iterator yielding list of documents
        """

        for _query in self.queries:
            yield self.reader.read(query=_query)
