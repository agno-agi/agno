"""
PageIndex Knowledge
===================
A Knowledge implementation that indexes PDF and Markdown documents into
hierarchical structures (using an LLM), then provides keyword-based
retrieval over the extracted sections.

Implements the KnowledgeProtocol and provides tools:
- search_documents: keyword search across indexed documents
- list_documents: list all indexed documents
- get_document_structure: view the hierarchical structure of a document

No vector database or embeddings are required — retrieval uses keyword
ranking over LLM-extracted section titles and summaries.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Literal, Optional

from agno.knowledge.document import Document
from agno.knowledge.pageindex.config import PageIndexSettings
from agno.knowledge.pageindex.registry import DocumentRegistry, RegistryRecord
from agno.knowledge.pageindex.schemas import BatchIndexResponse, IndexedDocument, RetrievalResult
from agno.utils.log import log_info, log_warning


@dataclass
class PageIndexKnowledge:
    """Knowledge implementation that indexes and searches PDF/Markdown documents.

    Uses LLM-powered hierarchy extraction to build a searchable structure
    from documents, then provides keyword-based retrieval (no embeddings).

    Example:
        ```python
        from agno.agent import Agent
        from agno.knowledge.pageindex import PageIndexKnowledge
        from agno.models.openai import OpenAIChat

        knowledge = PageIndexKnowledge(results_dir="./data")

        # Index a document (one-time, uses LLM)
        knowledge.index_file("report.pdf")

        agent = Agent(
            model=OpenAIChat(id="gpt-4o"),
            knowledge=knowledge,
            search_knowledge=True,
        )

        agent.print_response("What does the report say about revenue?")
        ```
    """

    # -- configuration ---------------------------------------------------------

    results_dir: str = "pageindex_results"
    upload_dir: str = "pageindex_uploads"
    tenant_id: str = "default"
    top_k_nodes: int = 6
    min_retrieval_score: int = 2
    max_evidence_chars: int = 9000
    structure_cache_size: int = 256
    llm_provider: str = "openai"
    openai_model: str = "gpt-4o-2024-11-20"
    anthropic_model: str = "claude-sonnet-4-6"
    ollama_model: str = "qwen2.5:7b"
    ollama_base_url: str = "http://localhost:11434/v1"
    model: Optional[str] = None

    # -- internal state --------------------------------------------------------

    _settings: Optional[PageIndexSettings] = field(default=None, init=False, repr=False)
    _registry: Optional[DocumentRegistry] = field(default=None, init=False, repr=False)
    _initialized: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self._ensure_initialized()

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self._settings = PageIndexSettings(
            tenant_id=self.tenant_id,
            llm_provider=self.llm_provider,
            model=self.model,
            openai_model=self.openai_model,
            anthropic_model=self.anthropic_model,
            ollama_model=self.ollama_model,
            ollama_base_url=self.ollama_base_url,
            results_dir=Path(self.results_dir),
            upload_dir=Path(self.upload_dir),
            top_k_nodes=self.top_k_nodes,
            min_retrieval_score=self.min_retrieval_score,
            max_evidence_chars=self.max_evidence_chars,
            structure_cache_size=self.structure_cache_size,
        )
        self._settings.prepare_environment()
        self._registry = DocumentRegistry(
            base_dir=self._settings.results_dir,
            tenant_id=self._settings.tenant_id,
        )
        self._initialized = True

    @property
    def settings(self) -> PageIndexSettings:
        self._ensure_initialized()
        assert self._settings is not None
        return self._settings

    @property
    def registry(self) -> DocumentRegistry:
        self._ensure_initialized()
        assert self._registry is not None
        return self._registry

    # ==========================================================================
    # Document management (public API)
    # ==========================================================================

    def index_file(
        self,
        path: str,
        doc_type: Optional[Literal["pdf", "md"]] = None,
        if_add_node_summary: str = "yes",
        if_add_doc_description: str = "no",
    ) -> IndexedDocument:
        """Index a single PDF or Markdown file.

        Uses an LLM to extract hierarchical structure from the document.
        Skips re-indexing if identical content (by SHA-256) is already indexed.

        Args:
            path: Path to the PDF or Markdown file.
            doc_type: Force document type (``"pdf"`` or ``"md"``). Auto-detected if ``None``.
            if_add_node_summary: Generate summaries for each section (``"yes"``/``"no"``).
            if_add_doc_description: Generate a one-line document description (``"yes"``/``"no"``).

        Returns:
            Metadata about the indexed document.
        """
        from agno.knowledge.pageindex.indexing import index_document

        log_info(f"PageIndex: indexing {path}")
        record = index_document(
            path=path,
            settings=self.settings,
            registry=self.registry,
            doc_type=doc_type,
            if_add_node_summary=if_add_node_summary,
            if_add_doc_description=if_add_doc_description,
        )
        return self._record_to_indexed_doc(record)

    def index_directory(
        self,
        directory: str,
        glob_pattern: str = "*.pdf",
        **index_kwargs,
    ) -> BatchIndexResponse:
        """Index all matching files in a directory.

        Args:
            directory: Directory containing documents.
            glob_pattern: Glob pattern to match files (default: ``"*.pdf"``).

        Returns:
            A response listing successfully indexed documents and failures.
        """
        from agno.knowledge.pageindex.indexing import index_document, list_candidate_files

        files = list_candidate_files(directory, glob_pattern)
        indexed: list[IndexedDocument] = []
        failed: list[str] = []

        for f in files:
            try:
                record = index_document(
                    path=str(f),
                    settings=self.settings,
                    registry=self.registry,
                    **index_kwargs,
                )
                indexed.append(self._record_to_indexed_doc(record))
            except Exception as exc:
                log_warning(f"PageIndex: failed to index {f}: {exc}")
                failed.append(str(f))

        return BatchIndexResponse(indexed=indexed, failed=failed)

    def index_bytes(
        self,
        filename: str,
        content: bytes,
        **index_kwargs,
    ) -> IndexedDocument:
        """Index a document from raw bytes (e.g., file upload).

        Args:
            filename: Original filename (used for type detection and storage).
            content: Raw file content.

        Returns:
            Metadata about the indexed document.
        """
        from agno.knowledge.pageindex.indexing import index_from_bytes

        record = index_from_bytes(
            filename=filename,
            content=content,
            settings=self.settings,
            registry=self.registry,
            **index_kwargs,
        )
        return self._record_to_indexed_doc(record)

    def list_indexed_documents(self) -> list[IndexedDocument]:
        """List all indexed documents."""
        return [self._record_to_indexed_doc(r) for r in self.registry.list()]

    def get_document(self, doc_id: str) -> Optional[IndexedDocument]:
        """Get metadata for a single indexed document."""
        record = self.registry.get(doc_id)
        if record is None:
            return None
        return self._record_to_indexed_doc(record)

    def get_structure(self, doc_id: str) -> Optional[dict]:
        """Get the hierarchical structure JSON of a document."""
        record = self.registry.get(doc_id)
        if record is None:
            return None
        try:
            with Path(record.structure_path).open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return None

    async def aindex_file(
        self,
        path: str,
        doc_type: Optional[Literal["pdf", "md"]] = None,
        if_add_node_summary: str = "yes",
        if_add_doc_description: str = "no",
    ) -> IndexedDocument:
        """Async version of :meth:`index_file`."""
        return await asyncio.to_thread(
            self.index_file,
            path,
            doc_type=doc_type,
            if_add_node_summary=if_add_node_summary,
            if_add_doc_description=if_add_doc_description,
        )

    async def aindex_directory(
        self,
        directory: str,
        glob_pattern: str = "*.pdf",
        **index_kwargs,
    ) -> BatchIndexResponse:
        """Async version of :meth:`index_directory`."""
        return await asyncio.to_thread(
            self.index_directory,
            directory,
            glob_pattern=glob_pattern,
            **index_kwargs,
        )

    async def aindex_bytes(
        self,
        filename: str,
        content: bytes,
        **index_kwargs,
    ) -> IndexedDocument:
        """Async version of :meth:`index_bytes`."""
        return await asyncio.to_thread(
            self.index_bytes,
            filename,
            content,
            **index_kwargs,
        )

    def delete_document(self, doc_id: str) -> bool:
        """Delete a document from the registry."""
        from agno.knowledge.pageindex.retrieval import invalidate_structure_cache

        record = self.registry.get(doc_id)
        if record is None:
            return False
        invalidate_structure_cache(record.structure_path)
        return self.registry.delete(doc_id)

    # ==========================================================================
    # KnowledgeProtocol implementation
    # ==========================================================================

    def build_context(self, **kwargs) -> str:
        docs = self.registry.list()
        doc_list = ", ".join(f"{r.doc_name} (id={r.doc_id})" for r in docs[:10]) or "none yet"
        return (
            "You have access to a PageIndex knowledge base with indexed documents.\n"
            "Use search_documents to find relevant sections by keyword.\n"
            "Use list_documents to see all available documents.\n"
            f"Currently indexed: {doc_list}"
        )

    def get_tools(self, **kwargs) -> List[Any]:
        return [
            self._create_search_tool(),
            self._create_list_tool(),
            self._create_structure_tool(),
        ]

    async def aget_tools(self, **kwargs) -> List[Any]:
        return self.get_tools(**kwargs)

    def retrieve(self, query: str, max_results: Optional[int] = None, **kwargs) -> List[Document]:
        """Retrieve documents for context injection (``add_knowledge_to_context``)."""
        from agno.knowledge.pageindex.retrieval import retrieve_multi

        records = self.registry.list()
        if not records:
            return []

        results = retrieve_multi(
            query=query,
            records=records,
            settings=self.settings,
            top_k=max_results or self.top_k_nodes,
        )
        return [self._result_to_document(r) for r in results if not r.insufficient_evidence]

    async def aretrieve(self, query: str, max_results: Optional[int] = None, **kwargs) -> List[Document]:
        """Async version of retrieve.

        Runs the blocking retrieval (file I/O + keyword ranking) in a thread
        so it does not block the event loop.
        """
        return await asyncio.to_thread(self.retrieve, query, max_results, **kwargs)

    # ==========================================================================
    # Tool factories
    # ==========================================================================

    def _create_search_tool(self) -> Any:
        from agno.tools.function import Function

        def search_documents(query: str, doc_id: str = "", top_k: int = 6) -> str:
            """Search indexed documents for relevant sections by keyword.

            Args:
                query: The search query (keywords or phrase).
                doc_id: Restrict search to a specific document ID. Leave empty to search all.
                top_k: Maximum number of results to return.

            Returns:
                Matching document sections with evidence text.
            """
            from agno.knowledge.pageindex.retrieval import retrieve as _retrieve
            from agno.knowledge.pageindex.retrieval import retrieve_multi

            if doc_id:
                record = self.registry.get(doc_id)
                if record is None:
                    return f"Document not found: {doc_id}"
                results = _retrieve(query, record, self.settings, top_k=top_k)
            else:
                records = self.registry.list()
                if not records:
                    return "No documents indexed yet."
                results = retrieve_multi(query, records, self.settings, top_k=top_k)

            if not results or all(r.insufficient_evidence for r in results):
                return "No relevant sections found for this query."

            parts = []
            for r in results:
                if r.insufficient_evidence:
                    continue
                header = f"### {r.title}"
                if r.doc_name:
                    header += f" ({r.doc_name})"
                parts.append(f"{header}\nScore: {r.score} | Pages: {r.start_index}-{r.end_index}\n{r.content}")
            return "\n\n---\n\n".join(parts)

        return Function.from_callable(search_documents, name="search_documents")

    def _create_list_tool(self) -> Any:
        from agno.tools.function import Function

        def list_documents() -> str:
            """List all indexed documents in the knowledge base.

            Returns:
                A summary of all indexed documents with their IDs and names.
            """
            records = self.registry.list()
            if not records:
                return "No documents indexed yet."

            lines = [f"Found {len(records)} indexed documents:"]
            for r in records:
                lines.append(f"- {r.doc_name} (id={r.doc_id}, type={r.doc_type})")
            return "\n".join(lines)

        return Function.from_callable(list_documents, name="list_documents")

    def _create_structure_tool(self) -> Any:
        from agno.tools.function import Function

        def get_document_structure(doc_id: str) -> str:
            """Get the hierarchical section structure of an indexed document.

            Args:
                doc_id: The document ID (use list_documents to find IDs).

            Returns:
                JSON representation of the document's section hierarchy.
            """
            structure = self.get_structure(doc_id)
            if structure is None:
                return f"Document not found or structure unavailable: {doc_id}"
            return json.dumps(structure, indent=2, ensure_ascii=False)

        return Function.from_callable(get_document_structure, name="get_document_structure")

    # ==========================================================================
    # Helpers
    # ==========================================================================

    @staticmethod
    def _record_to_indexed_doc(record: RegistryRecord) -> IndexedDocument:
        from datetime import datetime

        return IndexedDocument(
            doc_id=record.doc_id,
            doc_name=record.doc_name,
            doc_type=record.doc_type,
            source_path=record.source_path,
            structure_path=record.structure_path,
            indexed_at=datetime.fromisoformat(record.indexed_at.replace("Z", "+00:00")),
        )

    @staticmethod
    def _result_to_document(result: RetrievalResult) -> Document:
        return Document(
            content=result.content,
            name=result.title or result.doc_name,
            meta_data={
                "doc_id": result.doc_id,
                "doc_name": result.doc_name,
                "node_id": result.node_id,
                "start_index": result.start_index,
                "end_index": result.end_index,
                "score": result.score,
                "term_coverage": result.term_coverage,
                "source_path": result.source_path,
            },
        )
