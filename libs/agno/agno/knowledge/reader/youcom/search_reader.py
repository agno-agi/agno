from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Sequence

from agno.knowledge.chunking.strategy import ChunkingStrategy, ChunkingStrategyType
from agno.knowledge.document.base import Document
from agno.knowledge.reader.youcom.base import YouComReaderBase, _join_non_empty, _normalize_text, _slug
from agno.knowledge.types import ContentType


@dataclass
class YouSearchReader(YouComReaderBase):
    count: int = 5
    livecrawl: Optional[Literal["web", "news", "all"]] = None
    livecrawl_formats: Sequence[str] = ("markdown",)
    include_domains: Optional[List[str]] = None
    exclude_domains: Optional[List[str]] = None
    boost_domains: Optional[List[str]] = None
    country: Optional[str] = None
    freshness: Optional[str] = None
    language: Optional[str] = None
    safesearch: Optional[str] = None
    offset: Optional[int] = None
    crawl_timeout: int = 10
    search_params: Optional[Dict[str, Any]] = None

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        count: int = 5,
        livecrawl: Optional[Literal["web", "news", "all"]] = None,
        livecrawl_formats: Sequence[str] = ("markdown",),
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
        boost_domains: Optional[List[str]] = None,
        country: Optional[str] = None,
        freshness: Optional[str] = None,
        language: Optional[str] = None,
        safesearch: Optional[str] = None,
        offset: Optional[int] = None,
        crawl_timeout: int = 10,
        search_params: Optional[Dict[str, Any]] = None,
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
        if count <= 0:
            raise ValueError("count must be positive")
        if not 1 <= crawl_timeout <= 60:
            raise ValueError("crawl_timeout must be between 1 and 60 seconds")
        if offset is not None and not 0 <= offset <= 9:
            raise ValueError("offset must be between 0 and 9")
        if include_domains and (exclude_domains or boost_domains):
            raise ValueError("include_domains cannot be combined with exclude_domains or boost_domains")

        self.count = count
        self.livecrawl = livecrawl
        if isinstance(livecrawl_formats, str):
            self.livecrawl_formats = tuple(part.strip() for part in livecrawl_formats.split(",") if part.strip())
        else:
            self.livecrawl_formats = tuple(livecrawl_formats)
        self.include_domains = include_domains
        self.exclude_domains = exclude_domains
        self.boost_domains = boost_domains
        self.country = country
        self.freshness = freshness
        self.language = language
        self.safesearch = safesearch
        self.offset = offset
        self.crawl_timeout = crawl_timeout
        self.search_params = search_params

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

    def _build_params(self, query: str) -> Dict[str, Any]:
        params: Dict[str, Any] = {"query": query, "count": self.count}
        if self.livecrawl:
            params["livecrawl"] = self.livecrawl
            params["crawl_timeout"] = self.crawl_timeout
            params["livecrawl_formats"] = list(self.livecrawl_formats)
        if self.include_domains:
            params["include_domains"] = ",".join(self.include_domains)
        if self.exclude_domains:
            params["exclude_domains"] = ",".join(self.exclude_domains)
        if self.boost_domains:
            params["boost_domains"] = ",".join(self.boost_domains)
        if self.country:
            params["country"] = self.country
        if self.freshness:
            params["freshness"] = self.freshness
        if self.language:
            params["language"] = self.language
        if self.safesearch:
            params["safesearch"] = self.safesearch
        if self.offset is not None:
            params["offset"] = self.offset
        if self.search_params:
            params.update(self.search_params)
        return params

    def _parse_result(self, query: str, result: Dict[str, Any], section: str, index: int) -> List[Document]:
        url = result.get("url", "")
        title = result.get("title") or url or f"Result {index + 1}"
        description = _normalize_text(result.get("description"))
        snippets = result.get("snippets")
        snippet_text = ""
        if isinstance(snippets, list):
            snippet_text = "\n".join(snippet for snippet in snippets if isinstance(snippet, str))
        contents = result.get("contents")
        content_text = ""
        if isinstance(contents, dict):
            content_text = _normalize_text(contents.get("markdown") or contents.get("text") or contents.get("html") or contents.get("content"))
        content = _join_non_empty(
            [
                f"# {title}",
                f"Source: {url}" if url else "",
                description,
                snippet_text,
                content_text,
            ]
        )
        meta_data = {
            "query": query,
            "source": "youcom_search",
            "section": section,
            "result_index": index,
            "url": url,
            "title": title,
        }
        if result.get("page_age"):
            meta_data["page_age"] = result["page_age"]
        if result.get("published_date"):
            meta_data["published_date"] = result["published_date"]
        if result.get("favicon_url"):
            meta_data["favicon_url"] = result["favicon_url"]
        return self._document_from_text(
            doc_id=url or f"youcom:search:{_slug(query)}:{section}:{index}",
            name=title,
            content=content,
            meta_data=meta_data,
        )

    def _documents_from_response(self, query: str, data: Any) -> List[Document]:
        if not isinstance(data, dict):
            return []
        results = data.get("results")
        if not results:
            return []
        documents: List[Document] = []
        if isinstance(results, dict):
            for section, items in results.items():
                if not isinstance(items, list):
                    continue
                for index, result in enumerate(items):
                    if isinstance(result, dict):
                        documents.extend(self._parse_result(query, result, section, index))
        elif isinstance(results, list):
            for index, result in enumerate(results):
                if isinstance(result, dict):
                    documents.extend(self._parse_result(query, result, "web", index))
        return documents

    def read(self, query: str, name: Optional[str] = None) -> List[Document]:
        query = self._ensure_query(query)
        try:
            self.request_timeout = self._request_timeout_or_default(self.crawl_timeout)
            data = self._json_request("GET", "/v1/search", params=self._build_params(query))
            return self._documents_from_response(query, data)
        except Exception as error:
            self._log_request_error("You.com search request failed", error)
            return []

    async def async_read(self, query: str, name: Optional[str] = None) -> List[Document]:
        query = self._ensure_query(query)
        try:
            self.request_timeout = self._request_timeout_or_default(self.crawl_timeout)
            data = await self._async_json_request("GET", "/v1/search", params=self._build_params(query))
            return self._documents_from_response(query, data)
        except Exception as error:
            self._log_request_error("You.com search request failed", error)
            return []
