"""Operator-side toolkit for managing a knowledge base: ingest, list, remove.

The write side of knowledge. `KnowledgeTools` (think/search) is what an end-user-facing agent
gets; this toolkit is what a builder or operator agent gets, so widening one never leaks write
capability into product agents. Everything goes through the Knowledge API — no direct SQL.
"""

import json
import os
import time
from typing import Any, Dict, List, Literal, Optional

from agno.knowledge.content import Content, FileData
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.utils import get_agno_metadata, strip_agno_metadata
from agno.run import RunContext
from agno.tools import Toolkit
from agno.utils.log import log_error
from agno.utils.string import generate_id

_HARD_PAGE_CAP = 500
_LIST_PAGE_SIZE = 100
_SAMPLE_SIZE = 5

DEFAULT_INSTRUCTIONS = """\
You manage this platform's knowledge base.

- `ingest_url` loads a website page by page from its sitemap: one row per page, source URL
  kept. Point it at the docs subdomain rather than a marketing root. Re-running it refreshes
  pages that changed, retries pages that failed, and drops pages that left the site.
- `list_content` shows what is loaded, grouped by site. `ingest_status` reports one site.
- `remove_content` deletes a site row with every page under it, or one page row.
Report the returned numbers (pages loaded, failures) back to the operator plainly.\
"""


class KnowledgeManagementTools(Toolkit):
    """Manage a knowledge base: ingest websites and text, list what is loaded, remove it."""

    def __init__(
        self,
        knowledge: Knowledge,
        *,
        scope: Literal["shared", "user"] = "shared",
        max_pages: int = 50,
        page_fetcher: Optional[Any] = None,
        ingest_url: bool = True,
        ingest_path: bool = False,
        ingest_text: bool = True,
        remove_content: bool = True,
        instructions: Optional[str] = None,
        add_instructions: bool = True,
        **kwargs,
    ):
        """
        Args:
            knowledge: The knowledge base to manage.
            scope: Who owns what this toolkit writes. "shared" (default) writes rows every
                user can read — right for product docs. "user" writes rows owned by the
                run's user.
            max_pages: Default page cap for ingest_url (hard cap 500).
            page_fetcher: Optional PageFetcher for ingest_url; default resolves Parallel
                when available, the built-in fetcher otherwise.
            ingest_url: Register ingest_url, which fetches any URL the server can reach.
            ingest_path: Register ingest_path. Off by default: it reads any path the server
                process can read, and under scope="shared" what it loads becomes readable
                by every agent on this knowledge base.
            ingest_text: Register ingest_text, which stores text the agent already holds.
            remove_content: Register remove_content (requires confirmation by default).

        list_content and ingest_status are always registered — they only read.
        """
        if knowledge is None:
            raise ValueError("knowledge must be provided when using KnowledgeManagementTools")
        if getattr(knowledge, "contents_db", None) is None:
            # Every tool here reads or writes content rows (status, listing, digests,
            # cascade delete); on a vector-only base they would silently half-work.
            raise ValueError(
                "KnowledgeManagementTools requires a Knowledge with a contents_db "
                "(e.g. Knowledge(vector_db=..., contents_db=SqliteDb(...)))"
            )
        self.knowledge = knowledge
        self.scope = scope
        self.max_pages = max(1, min(max_pages, _HARD_PAGE_CAP))
        self.page_fetcher = page_fetcher

        # Each flag is named after the tool it registers. They stay locals — assigning one
        # to self would shadow the method of the same name.
        tools: List[Any] = []
        async_tools: List[Any] = []
        if ingest_url:
            tools.append(self.ingest_url)
            async_tools.append((self.aingest_url, "ingest_url"))
        if ingest_path:
            tools.append(self.ingest_path)
            async_tools.append((self.aingest_path, "ingest_path"))
        if ingest_text:
            tools.append(self.ingest_text)
            async_tools.append((self.aingest_text, "ingest_text"))
        tools.append(self.list_content)
        async_tools.append((self.alist_content, "list_content"))
        tools.append(self.ingest_status)
        async_tools.append((self.aingest_status, "ingest_status"))
        if remove_content:
            tools.append(self.remove_content)
            async_tools.append((self.aremove_content, "remove_content"))
            # Union, not setdefault: a caller naming other tools must not drop the
            # confirmation gate on the one tool here that destroys data.
            kwargs["requires_confirmation_tools"] = list(
                dict.fromkeys(["remove_content", *(kwargs.get("requires_confirmation_tools") or [])])
            )

        super().__init__(
            name="knowledge_management",
            tools=tools,
            async_tools=async_tools,
            instructions=instructions if instructions is not None else DEFAULT_INSTRUCTIONS,
            add_instructions=add_instructions,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _owner_id(self, run_context: Optional[RunContext]) -> Optional[str]:
        if self.scope == "user":
            user_id = getattr(run_context, "user_id", None)
            if not user_id:
                # Fail closed: scope="user" content silently landing in the shared
                # bucket would be readable and deletable by everyone.
                raise ValueError("scope='user' requires the run to have a user_id")
            return user_id
        return None

    def _build_reader(self, max_pages: Optional[int]):
        from agno.knowledge.reader.sitemap_reader import SitemapReader

        cap = max(1, min(int(max_pages), _HARD_PAGE_CAP)) if max_pages else self.max_pages
        if self.page_fetcher is not None:
            return SitemapReader(max_pages=cap, page_fetcher=self.page_fetcher)
        return SitemapReader(max_pages=cap)

    def _predict_url_row_id(self, url: str, owner: Optional[str]) -> str:
        # The same Content shape ainsert(url=..., user_id=...) builds, so the hash — and the
        # row id — match what the insert writes.
        content = Content(url=url, user_id=owner)
        return generate_id(self.knowledge._build_content_hash(content))

    def _predict_text_row_id(
        self, name: str, text: str, metadata: Optional[Dict[str, Any]], owner: Optional[str]
    ) -> str:
        # Mirror the Content shape ainsert(text_content=...) builds — the file_data branch of
        # the hash only engages when content is non-empty, so the real text goes in.
        content = Content(
            name=name,
            file_data=FileData(content=text, type="Text"),
            metadata=strip_agno_metadata(metadata),
            user_id=owner,
        )
        return generate_id(self.knowledge._build_content_hash(content))

    @staticmethod
    def _error(message: str) -> str:
        return json.dumps({"ok": False, "error": message})

    @staticmethod
    def _status_value(status: Any) -> str:
        return str(getattr(status, "value", status) or "").lower()

    def _site_report(self, row: Optional[Content], site_id: str, seconds: Optional[float] = None) -> str:
        if row is None:
            return self._error(f"content {site_id} not found")
        meta = row.metadata or {}
        status = self._status_value(row.status)
        report: Dict[str, Any] = {
            "ok": status != "failed",
            "site_id": site_id,
            "name": row.name,
            "status": status,
            "status_message": row.status_message,
            "pages": get_agno_metadata(meta, "page_count"),
            "failed": get_agno_metadata(meta, "failed") or [],
            "extractors": get_agno_metadata(meta, "extractor_counts") or {},
        }
        children = get_agno_metadata(meta, "children")
        if isinstance(children, list):
            report["page_rows"] = len(children)
        if seconds is not None:
            report["seconds"] = round(seconds, 1)
        return json.dumps(report, default=str)

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------

    def ingest_url(self, run_context: RunContext, url: str, max_pages: Optional[int] = None) -> str:
        """Ingest a website into the knowledge base, one row per page with its source URL.

        Discovers pages from the site's sitemap (robots.txt and sitemap indexes are
        followed). A site without a sitemap gets the one page at `url`. Re-running refreshes
        changed pages, retries failed ones, and removes pages that left the site.

        Args:
            url: Any page of the site, e.g. https://docs.example.com. Prefer the docs subdomain.
            max_pages: Maximum pages to ingest (default from the toolkit, hard cap 500).

        Returns:
            JSON: ok, site_id, name, status, pages, failed (per-URL errors), extractors, seconds.
        """
        started = time.monotonic()
        try:
            owner = self._owner_id(run_context)
            site_id = self._predict_url_row_id(url, owner)
            self.knowledge.insert(url=url, reader=self._build_reader(max_pages), user_id=owner)
            row = self.knowledge.get_content_by_id(site_id, user_id=owner)
            return self._site_report(row, site_id, seconds=time.monotonic() - started)
        except Exception as e:
            log_error(f"ingest_url failed for {url}: {e}")
            return self._error(str(e))

    async def aingest_url(self, run_context: RunContext, url: str, max_pages: Optional[int] = None) -> str:
        """Ingest a website into the knowledge base, one row per page with its source URL.

        Discovers pages from the site's sitemap (robots.txt and sitemap indexes are
        followed). A site without a sitemap gets the one page at `url`. Re-running refreshes
        changed pages, retries failed ones, and removes pages that left the site.

        Args:
            url: Any page of the site, e.g. https://docs.example.com. Prefer the docs subdomain.
            max_pages: Maximum pages to ingest (default from the toolkit, hard cap 500).

        Returns:
            JSON: ok, site_id, name, status, pages, failed (per-URL errors), extractors, seconds.
        """
        started = time.monotonic()
        try:
            owner = self._owner_id(run_context)
            site_id = self._predict_url_row_id(url, owner)
            await self.knowledge.ainsert(url=url, reader=self._build_reader(max_pages), user_id=owner)
            row = await self.knowledge.aget_content_by_id(site_id, user_id=owner)
            return self._site_report(row, site_id, seconds=time.monotonic() - started)
        except Exception as e:
            log_error(f"ingest_url failed for {url}: {e}")
            return self._error(str(e))

    def _predict_path_row_id(self, path: str, owner: Optional[str]) -> str:
        # The same Content shape insert(path=...) builds, so the returned id is the row's
        content = Content(path=path, user_id=owner)
        return generate_id(self.knowledge._build_content_hash(content))

    def ingest_path(self, run_context: RunContext, path: str) -> str:
        """Ingest a local file or folder into the knowledge base.

        A folder lands one row per file (nested folders included) under a folder row;
        re-running refreshes files whose content changed, retries failed ones, and
        removes rows for files deleted from the folder. A single file lands as one row.

        Args:
            path: A file or directory path readable by the server, e.g. /data/product-docs.

        Returns:
            JSON: ok, site_id (the row to use with ingest_status/remove_content), name,
            status, status_message, and for folders pages (files loaded) and failed.
        """
        started = time.monotonic()
        try:
            if not os.path.exists(path):
                return self._error(f"path does not exist: {path}")
            owner = self._owner_id(run_context)
            row_id = self._predict_path_row_id(path, owner)
            self.knowledge.insert(path=path, user_id=owner)
            row = self.knowledge.get_content_by_id(row_id, user_id=owner)
            return self._site_report(row, row_id, seconds=time.monotonic() - started)
        except Exception as e:
            log_error(f"ingest_path failed for {path}: {e}")
            return self._error(str(e))

    async def aingest_path(self, run_context: RunContext, path: str) -> str:
        """Ingest a local file or folder into the knowledge base.

        A folder lands one row per file (nested folders included) under a folder row;
        re-running refreshes files whose content changed, retries failed ones, and
        removes rows for files deleted from the folder. A single file lands as one row.

        Args:
            path: A file or directory path readable by the server, e.g. /data/product-docs.

        Returns:
            JSON: ok, site_id (the row to use with ingest_status/remove_content), name,
            status, status_message, and for folders pages (files loaded) and failed.
        """
        started = time.monotonic()
        try:
            if not os.path.exists(path):
                return self._error(f"path does not exist: {path}")
            owner = self._owner_id(run_context)
            row_id = self._predict_path_row_id(path, owner)
            await self.knowledge.ainsert(path=path, user_id=owner)
            row = await self.knowledge.aget_content_by_id(row_id, user_id=owner)
            return self._site_report(row, row_id, seconds=time.monotonic() - started)
        except Exception as e:
            log_error(f"ingest_path failed for {path}: {e}")
            return self._error(str(e))

    def ingest_text(
        self, run_context: RunContext, name: str, text: str, metadata: Optional[Dict[str, str]] = None
    ) -> str:
        """Add a piece of text to the knowledge base as one named document.

        Args:
            name: A short, unique name for the document.
            text: The document text.
            metadata: Optional metadata key-value pairs stored with the document.

        Returns:
            JSON: ok, id, name.
        """
        try:
            owner = self._owner_id(run_context)
            self.knowledge.insert(name=name, text_content=text, metadata=metadata, user_id=owner)
            row_id = self._predict_text_row_id(name, text, metadata, owner)
            row = self.knowledge.get_content_by_id(row_id, user_id=owner) if self.knowledge.contents_db else None
            if row is not None and self._status_value(row.status) == "failed":
                return json.dumps({"ok": False, "id": row_id, "name": name, "error": row.status_message})
            return json.dumps({"ok": True, "id": row_id, "name": name})
        except Exception as e:
            log_error(f"ingest_text failed for {name}: {e}")
            return self._error(str(e))

    async def aingest_text(
        self, run_context: RunContext, name: str, text: str, metadata: Optional[Dict[str, str]] = None
    ) -> str:
        """Add a piece of text to the knowledge base as one named document.

        Args:
            name: A short, unique name for the document.
            text: The document text.
            metadata: Optional metadata key-value pairs stored with the document.

        Returns:
            JSON: ok, id, name.
        """
        try:
            owner = self._owner_id(run_context)
            await self.knowledge.ainsert(name=name, text_content=text, metadata=metadata, user_id=owner)
            row_id = self._predict_text_row_id(name, text, metadata, owner)
            row = await self.knowledge.aget_content_by_id(row_id, user_id=owner) if self.knowledge.contents_db else None
            if row is not None and self._status_value(row.status) == "failed":
                return json.dumps({"ok": False, "id": row_id, "name": name, "error": row.status_message})
            return json.dumps({"ok": True, "id": row_id, "name": name})
        except Exception as e:
            log_error(f"ingest_text failed for {name}: {e}")
            return self._error(str(e))

    # ------------------------------------------------------------------
    # List / status
    # ------------------------------------------------------------------

    def _group_rows(self, rows: List[Content], host: Optional[str]) -> str:
        sites: List[Dict[str, Any]] = []
        pages_by_parent: Dict[str, int] = {}
        other: List[Dict[str, Any]] = []
        for row in rows:
            meta = row.metadata or {}
            parent_id = get_agno_metadata(meta, "parent_id")
            if isinstance(parent_id, str):
                pages_by_parent[parent_id] = pages_by_parent.get(parent_id, 0) + 1
                continue
            children = get_agno_metadata(meta, "children")
            if isinstance(children, list):
                sites.append(
                    {
                        "site_id": row.id,
                        "name": row.name,
                        "pages": len(children),
                        "failed": len(get_agno_metadata(meta, "failed") or []),
                        "status": self._status_value(row.status),
                        "updated_at": row.updated_at,
                    }
                )
            else:
                other.append(
                    {"id": row.id, "name": row.name, "type": row.file_type, "status": self._status_value(row.status)}
                )
        if host:
            needle = host.lower()
            sites = [site for site in sites if needle in (site["name"] or "").lower()]
            other = [entry for entry in other if needle in (entry["name"] or "").lower()]
        return json.dumps({"sites": sites, "other": other, "total_rows": len(rows)}, default=str)

    def list_content(self, run_context: RunContext, host: Optional[str] = None) -> str:
        """List what the knowledge base holds, grouped by ingested site.

        Args:
            host: Optional host filter, e.g. "docs.example.com" — only entries whose name
                contains it are returned.

        Returns:
            JSON: sites (site_id, name, pages, failed, status, updated_at), other documents,
            and the total row count.
        """
        try:
            owner = self._owner_id(run_context)
            rows: List[Content] = []
            page = 1
            while True:
                batch, count = self.knowledge.get_content(limit=_LIST_PAGE_SIZE, page=page, user_id=owner)
                rows.extend(batch)
                if len(rows) >= count or not batch:
                    break
                page += 1
            return self._group_rows(rows, host)
        except Exception as e:
            log_error(f"list_content failed: {e}")
            return self._error(str(e))

    async def alist_content(self, run_context: RunContext, host: Optional[str] = None) -> str:
        """List what the knowledge base holds, grouped by ingested site.

        Args:
            host: Optional host filter, e.g. "docs.example.com" — only entries whose name
                contains it are returned.

        Returns:
            JSON: sites (site_id, name, pages, failed, status, updated_at), other documents,
            and the total row count.
        """
        try:
            owner = self._owner_id(run_context)
            rows = []
            page = 1
            while True:
                batch, count = await self.knowledge.aget_content(limit=_LIST_PAGE_SIZE, page=page, user_id=owner)
                rows.extend(batch)
                if len(rows) >= count or not batch:
                    break
                page += 1
            return self._group_rows(rows, host)
        except Exception as e:
            log_error(f"list_content failed: {e}")
            return self._error(str(e))

    def ingest_status(self, run_context: RunContext, site_id: str) -> str:
        """Report one ingested site: status, pages loaded, and per-page failures.

        Args:
            site_id: The site row id returned by ingest_url or list_content.

        Returns:
            JSON: ok, site_id, name, status, status_message, pages, failed, extractors.
        """
        try:
            owner = self._owner_id(run_context)
            row = self.knowledge.get_content_by_id(site_id, user_id=owner)
            return self._site_report(row, site_id)
        except Exception as e:
            log_error(f"ingest_status failed for {site_id}: {e}")
            return self._error(str(e))

    async def aingest_status(self, run_context: RunContext, site_id: str) -> str:
        """Report one ingested site: status, pages loaded, and per-page failures.

        Args:
            site_id: The site row id returned by ingest_url or list_content.

        Returns:
            JSON: ok, site_id, name, status, status_message, pages, failed, extractors.
        """
        try:
            owner = self._owner_id(run_context)
            row = await self.knowledge.aget_content_by_id(site_id, user_id=owner)
            return self._site_report(row, site_id)
        except Exception as e:
            log_error(f"ingest_status failed for {site_id}: {e}")
            return self._error(str(e))

    # ------------------------------------------------------------------
    # Remove
    # ------------------------------------------------------------------

    def remove_content(self, run_context: RunContext, content_id: str) -> str:
        """Delete content from the knowledge base. Deleting a site removes every page under it.

        Args:
            content_id: A site row id (removes the site and all its pages) or a single
                document/page row id.

        Returns:
            JSON: ok and the id removed.
        """
        try:
            owner = self._owner_id(run_context)
            row = self.knowledge.get_content_by_id(content_id, user_id=owner)
            if row is None:
                return self._error(f"content {content_id} not found")
            removed = self.knowledge.remove_content_by_id(content_id, user_id=owner)
            if removed is False:
                return self._error(f"content {content_id} was not removed (delete refused or vector store failed)")
            return json.dumps({"ok": True, "removed": content_id, "name": row.name})
        except Exception as e:
            log_error(f"remove_content failed for {content_id}: {e}")
            return self._error(str(e))

    async def aremove_content(self, run_context: RunContext, content_id: str) -> str:
        """Delete content from the knowledge base. Deleting a site removes every page under it.

        Args:
            content_id: A site row id (removes the site and all its pages) or a single
                document/page row id.

        Returns:
            JSON: ok and the id removed.
        """
        try:
            owner = self._owner_id(run_context)
            row = await self.knowledge.aget_content_by_id(content_id, user_id=owner)
            if row is None:
                return self._error(f"content {content_id} not found")
            removed = await self.knowledge.aremove_content_by_id(content_id, user_id=owner)
            if removed is False:
                return self._error(f"content {content_id} was not removed (delete refused or vector store failed)")
            return json.dumps({"ok": True, "removed": content_id, "name": row.name})
        except Exception as e:
            log_error(f"remove_content failed for {content_id}: {e}")
            return self._error(str(e))
