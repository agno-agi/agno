"""KnowledgeCatalog — document-level index for agent system prompt injection.

Gives agents awareness of what documents exist in the knowledge base
without requiring a search query. The catalog is injected into the
system prompt so the agent knows what content is available.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agno.knowledge.store.content_store import ContentStore
from agno.utils.log import log_debug, log_warning


@dataclass
class KnowledgeCatalog:
    """Builds a document catalog from the ContentStore for system prompt injection."""

    content_store: Optional[ContentStore] = None
    knowledge_name: Optional[str] = None
    _cached_summaries: Optional[List[Dict[str, Any]]] = field(default=None, repr=False)

    def get_summaries(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get a list of document summaries from the content store."""
        if self.content_store is None or self.content_store.contents_db is None:
            return []

        try:
            contents, _ = self.content_store.get_content(limit=limit)
        except Exception as e:
            log_warning(f"Could not fetch content for catalog: {e}")
            return []

        summaries = []
        for content in contents:
            summary: Dict[str, Any] = {}
            if content.id:
                summary["id"] = content.id
            if content.name:
                summary["name"] = content.name
            if content.description:
                summary["description"] = content.description
            if content.file_type:
                summary["type"] = content.file_type
            if content.status:
                summary["status"] = content.status.value if hasattr(content.status, "value") else str(content.status)
            if summary:
                summaries.append(summary)
        return summaries

    async def aget_summaries(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Async variant of get_summaries."""
        if self.content_store is None or self.content_store.contents_db is None:
            return []

        try:
            contents, _ = await self.content_store.aget_content(limit=limit)
        except Exception as e:
            log_warning(f"Could not fetch content for catalog: {e}")
            return []

        summaries = []
        for content in contents:
            summary: Dict[str, Any] = {}
            if content.id:
                summary["id"] = content.id
            if content.name:
                summary["name"] = content.name
            if content.description:
                summary["description"] = content.description
            if content.file_type:
                summary["type"] = content.file_type
            if content.status:
                summary["status"] = content.status.value if hasattr(content.status, "value") else str(content.status)
            if summary:
                summaries.append(summary)
        return summaries

    def build_catalog_context(self) -> str:
        """Build a formatted catalog string for system prompt injection."""
        summaries = self.get_summaries()
        return self._format_catalog(summaries)

    async def abuild_catalog_context(self) -> str:
        """Async variant of build_catalog_context."""
        summaries = await self.aget_summaries()
        return self._format_catalog(summaries)

    def _format_catalog(self, summaries: List[Dict[str, Any]]) -> str:
        """Format document summaries into a readable catalog string."""
        if not summaries:
            return ""

        lines = ["The following documents are available in the knowledge base:"]
        for i, summary in enumerate(summaries, 1):
            name = summary.get("name", "Unknown")
            desc = summary.get("description", "")
            doc_type = summary.get("type", "")
            parts = [f"{i}. {name}"]
            if doc_type:
                parts.append(f"({doc_type})")
            if desc:
                parts.append(f"- {desc}")
            lines.append(" ".join(parts))

        return "\n".join(lines)

    def get_tools(self) -> List[Any]:
        """Return a list_documents Function tool for the agent."""
        from agno.tools.function import Function

        catalog = self

        def list_documents() -> str:
            """List all documents available in the knowledge base.

            Returns:
                str: A formatted list of documents with their names and descriptions.
            """
            summaries = catalog.get_summaries()
            if not summaries:
                return "No documents found in the knowledge base."
            return catalog._format_catalog(summaries)

        async def alist_documents() -> str:
            """List all documents available in the knowledge base (async).

            Returns:
                str: A formatted list of documents with their names and descriptions.
            """
            summaries = await catalog.aget_summaries()
            if not summaries:
                return "No documents found in the knowledge base."
            return catalog._format_catalog(summaries)

        tool = Function(
            name="list_documents",
            description="List all documents available in the knowledge base with their names and descriptions.",
            entrypoint=list_documents,
            async_entrypoint=alist_documents,
        )
        log_debug("Created list_documents tool from KnowledgeCatalog")
        return [tool]
