from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from agno.knowledge.chunking.strategy import ChunkingStrategy, ChunkingStrategyType
from agno.knowledge.document.base import Document
from agno.knowledge.reader.youcom.base import YouComReaderBase, _join_non_empty, _normalize_text, _slug
from agno.knowledge.types import ContentType


@dataclass
class YouFinanceResearchReader(YouComReaderBase):
    research_effort: str = "deep"
    include_source_documents: bool = False

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        research_effort: str = "deep",
        include_source_documents: bool = False,
        request_timeout: Optional[float] = None,
        chunk: bool = True,
        chunk_size: int = 5000,
        chunking_strategy: Optional[ChunkingStrategy] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            request_timeout=request_timeout,
            chunk=chunk,
            chunk_size=chunk_size,
            chunking_strategy=chunking_strategy,
            name=name,
            description=description,
        )
        if not research_effort:
            raise ValueError("research_effort cannot be empty")
        self.research_effort = research_effort
        self.include_source_documents = include_source_documents

    @classmethod
    def get_supported_chunking_strategies(cls) -> List[ChunkingStrategyType]:
        return [
            ChunkingStrategyType.CODE_CHUNKER,
            ChunkingStrategyType.SEMANTIC_CHUNKER,
            ChunkingStrategyType.FIXED_SIZE_CHUNKER,
            ChunkingStrategyType.AGENTIC_CHUNKER,
            ChunkingStrategyType.DOCUMENT_CHUNKER,
            ChunkingStrategyType.RECURSIVE_CHUNKER,
        ]

    @classmethod
    def get_supported_content_types(cls) -> List[ContentType]:
        return [ContentType.TOPIC]

    def _build_payload(self, query: str) -> Dict[str, Any]:
        return {
            "input": query,
            "research_effort": self.research_effort,
        }

    def _documents_from_response(self, query: str, data: Any) -> List[Document]:
        if not isinstance(data, dict):
            return []
        output = data.get("output") if isinstance(data.get("output"), dict) else data
        if not isinstance(output, dict):
            return []
        content = output.get("content")
        if content is None:
            return []
        content_text = _normalize_text(content)
        sources = output.get("sources") or []
        documents = self._document_from_text(
            doc_id=f"youcom:finance:{_slug(query)}",
            name=query,
            content=content_text,
            meta_data={
                "source": "youcom_finance_research",
                "input": query,
                "research_effort": self.research_effort,
                "content_type": output.get("content_type", "text"),
                "source_count": len(sources) if isinstance(sources, list) else 0,
            },
        )
        if not self.include_source_documents or not isinstance(sources, list):
            return documents
        for index, source in enumerate(sources):
            if not isinstance(source, dict):
                continue
            url = source.get("url", "")
            title = source.get("title") or url or f"Source {index + 1}"
            source_content = _join_non_empty(
                [
                    f"# {title}",
                    f"Source: {url}" if url else "",
                    _normalize_text(source.get("description")),
                    _normalize_text(source.get("snippet") or source.get("content") or source.get("markdown") or source.get("text")),
                ]
            )
            documents.extend(
                self._document_from_text(
                    doc_id=url or f"youcom:finance:{_slug(query)}:source:{index}",
                    name=title,
                    content=source_content,
                    meta_data={
                        "source": "youcom_finance_research_source",
                        "input": query,
                        "research_effort": self.research_effort,
                        "source_index": index,
                        "url": url,
                        "title": title,
                    },
                )
            )
        return documents

    def read(self, query: str, name: Optional[str] = None) -> List[Document]:
        query = self._ensure_query(query)
        try:
            data = self._json_request("POST", "/v1/finance_research", json_body=self._build_payload(query))
            return self._documents_from_response(query, data)
        except Exception as error:
            self._log_request_error("You.com finance research request failed", error)
            return []

    async def async_read(self, query: str, name: Optional[str] = None) -> List[Document]:
        query = self._ensure_query(query)
        try:
            data = await self._async_json_request("POST", "/v1/finance_research", json_body=self._build_payload(query))
            return self._documents_from_response(query, data)
        except Exception as error:
            self._log_request_error("You.com finance research request failed", error)
            return []
