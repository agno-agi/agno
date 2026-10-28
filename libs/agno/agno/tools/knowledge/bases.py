"""KnowledgeBaseTools -- give agents the ability to manage an AgentOS's knowledge bases.

``KnowledgeManagementTools`` manages the one knowledge base handed to it. This toolkit
manages every knowledge base it is given, addressed by the same id (or name) the OS UI
and ``/knowledge`` routes use, so an operator agent can load, inspect, search and remove
content across the whole platform.

Writes take the path ``POST /knowledge/content`` takes, so a row added here is the same
row a UI upload of that source would write. Permissions mirror the routes' scopes
(knowledge:read / knowledge:write / knowledge:delete), and owner scoping mirrors
``get_scoped_user_id``.

Example:
    from agno.tools.knowledge import KnowledgeBaseTools

    agent = Agent(
        model=OpenAIChat(id="gpt-5.5"),
        tools=[KnowledgeBaseTools(knowledge=[docs_kb, support_kb])],
    )
"""

import json
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union
from urllib.parse import urlparse

from agno.db.base import AsyncBaseDb
from agno.knowledge.content import Content, FileData
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.base import Reader
from agno.knowledge.utils import strip_agno_metadata
from agno.media import File
from agno.run import RunContext
from agno.run.authorization import current_authorization, requires_permission
from agno.tools.toolkit import Toolkit
from agno.utils.log import logger
from agno.utils.string import generate_id

_MAX_LIST_LIMIT = 100
_MAX_SEARCH_LIMIT = 20
_SNIPPET_CHARS = 500
# What the OS knowledge upload accepts, plus .pptx which Knowledge reads natively. Other
# chat attachments (zip, eml, source code) would fall through to the text reader.
_LOADABLE_EXTENSIONS = {
    ".pdf", ".csv", ".json", ".txt", ".doc", ".docx", ".md", ".rtf",
    ".html", ".htm", ".xml", ".xlsx", ".xls", ".pptx",
}  # fmt: skip

DEFAULT_INSTRUCTIONS = """\
Use these tools to manage the platform's knowledge bases.

- Start with `list_knowledge_bases`; every other tool takes a base's `id` (or exact name).
- `add_url` loads a web page, file URL, sitemap or llms.txt. An llms.txt URL is read with the
  llms.txt reader, which loads every linked documentation page, so prefer a site's llms.txt
  when it has one. Pass `reader_id` only to override that choice.
- `add_text` stores text you already hold under a unique name.
- `add_files` loads documents the user attached to their current message (PDF, DOCX, CSV, ...).
  It only sees this message's attachments: if none are attached, ask the user to attach them.
- `get_content` reports one row's status; `list_content` pages through what is loaded;
  `search_knowledge` shows what a query actually retrieves.
- `remove_content` deletes a row and its vectors.
Report the returned status and any status_message back plainly.\
"""


def _error(message: str, **details: Any) -> str:
    return json.dumps({"error": message, **details}, default=str)


def knowledge_base_id(knowledge: Any) -> Optional[str]:
    """The id AgentOS assigns a knowledge base, or None when it has no contents db."""
    contents_db = getattr(knowledge, "contents_db", None)
    db_id = getattr(contents_db, "id", None)
    if not db_id:
        return None
    from agno.os.utils import _generate_knowledge_id

    name = getattr(knowledge, "name", None) or f"knowledge_{db_id}"
    table = getattr(contents_db, "knowledge_table_name", None) or "unknown"
    return _generate_knowledge_id(name, db_id, table)


def _is_llms_txt(url: str) -> bool:
    try:
        path = urlparse(url).path
    except ValueError:
        return False
    return path.rstrip("/").lower().endswith("/llms.txt")


def _status(value: Any) -> Optional[str]:
    return str(getattr(value, "value", value)).lower() if value is not None else None


def _content_view(content: Content) -> Dict[str, Any]:
    return {
        "id": content.id,
        "name": content.name,
        "description": content.description,
        "type": content.file_type,
        "status": _status(content.status),
        "status_message": content.status_message,
        # Framework bookkeeping (indexing state, site children) stays out of the model's view.
        "metadata": strip_agno_metadata(content.metadata),
        "created_at": content.created_at,
        "updated_at": content.updated_at,
    }


def _filename(file: File) -> str:
    return file.filename or file.name or file.id or "file"


def _pick_files(files: Optional[Sequence[File]], filenames: Optional[List[str]]) -> Tuple[List[File], List[str]]:
    """The attached files to load, and any requested names that are not attached."""
    attached = list(files or [])
    if not filenames:
        return attached, []
    wanted = {name.strip(): name for name in filenames if name and name.strip()}
    picked = [f for f in attached if _filename(f) in wanted]
    found = {_filename(f) for f in picked}
    return picked, [name for key, name in wanted.items() if key not in found]


def _search_view(documents: List[Any]) -> List[Dict[str, Any]]:
    results = []
    for doc in documents:
        text = doc.content or ""
        results.append(
            {
                "name": doc.name,
                "content_id": getattr(doc, "content_id", None),
                "url": (doc.meta_data or {}).get("url"),
                "snippet": text[:_SNIPPET_CHARS] + ("..." if len(text) > _SNIPPET_CHARS else ""),
            }
        )
    return results


class KnowledgeBaseTools(Toolkit):
    """Toolkit that lets an agent load, inspect, search and remove content across knowledge bases.

    Args:
        knowledge: The knowledge bases to manage. Pass a LiveSequence (e.g. over
            ``agent_os.knowledge_instances``) when the list is discovered after the
            toolkit is built; it is read on every call.
        user_isolation: Deployment configuration, never a model argument. When true (or a
            callable returning true), reads and writes scope to the caller the way the
            ``/knowledge`` routes do under user isolation. Service accounts always scope
            to themselves, as they do over HTTP.
        add_content: Register add_url, add_text and add_files. Defaults to True.
        remove_content: Register remove_content, which requires confirmation. Defaults to True.

    list_knowledge_bases, list_content, get_content and search_knowledge are always
    registered: they only read.
    """

    def __init__(
        self,
        knowledge: Optional[Sequence[Any]] = None,
        user_isolation: Union[bool, Callable[[], bool]] = False,
        add_content: bool = True,
        remove_content: bool = True,
        instructions: Optional[str] = None,
        add_instructions: bool = True,
        **kwargs: Any,
    ):
        self.knowledge: Sequence[Any] = knowledge if knowledge is not None else []
        self.user_isolation = user_isolation

        names = ["list_knowledge_bases", "list_content", "get_content", "search_knowledge"]
        if add_content:
            names += ["add_url", "add_text", "add_files"]
        if remove_content:
            names.append("remove_content")
            # Union, not setdefault: naming other tools must not drop the gate on the
            # one tool here that destroys data.
            kwargs["requires_confirmation_tools"] = list(
                dict.fromkeys(["remove_content", *(kwargs.get("requires_confirmation_tools") or [])])
            )

        super().__init__(
            name="knowledge_bases",
            tools=[getattr(self, name) for name in names],
            async_tools=[(getattr(self, "a" + name), name) for name in names],
            instructions=instructions if instructions is not None else DEFAULT_INSTRUCTIONS,
            add_instructions=add_instructions,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _owner(self, run_context: Optional[RunContext]) -> Optional[str]:
        """The owner to scope to, or None for unscoped. Mirrors get_scoped_user_id."""
        authority = current_authorization() or getattr(run_context, "authorization", None)
        user = authority.context.principal_id if authority is not None else getattr(run_context, "user_id", None)
        if authority is not None:
            ctx = authority.context
            if (authority.service_account or authority.provider.enforces_token_scopes) and (
                (ctx.admin_scope or "agent_os:admin") in ctx.scopes
            ):
                return None
        isolated = self.user_isolation() if callable(self.user_isolation) else self.user_isolation
        if isolated or (isinstance(user, str) and user.startswith("sa:")):
            if not user:
                raise PermissionError("Caller identity is required under user isolation")
            return user
        return None

    def _bases(self) -> List[Tuple[str, Any]]:
        bases: List[Tuple[str, Any]] = []
        seen = set()
        for kb in self.knowledge:
            kb_id = knowledge_base_id(kb)
            if kb_id is None or kb_id in seen:
                continue
            seen.add(kb_id)
            bases.append((kb_id, kb))
        return bases

    def _find(self, ref: str, sync: bool = False) -> Tuple[Optional[Knowledge], Optional[str]]:
        """Resolve an id or exact name to a local Knowledge, or return an error JSON."""
        ref = (ref or "").strip()
        bases = self._bases()
        match = next((kb for kb_id, kb in bases if kb_id == ref), None)
        if match is None:
            named = [kb for _, kb in bases if getattr(kb, "name", None) == ref]
            if len(named) > 1:
                return None, _error(f"More than one knowledge base is named '{ref}'; use its id")
            match = named[0] if named else None
        if match is None:
            return None, _error(
                f"Knowledge base not found: {ref}",
                available=[{"id": kb_id, "name": getattr(kb, "name", None)} for kb_id, kb in bases],
            )
        if not isinstance(match, Knowledge):
            return None, _error("This knowledge base is served by a remote AgentOS; manage it there")
        if sync and isinstance(match.contents_db, AsyncBaseDb):
            return None, _error("This knowledge base has an async database; use the async tools")
        return match, None

    @staticmethod
    def _resolve_reader(kb: Knowledge, reader_id: Optional[str], url: Optional[str]) -> Tuple[Optional[Reader], Any]:
        """The reader for this upload: an explicit id, the llms.txt reader, or None for the default.

        An explicit id resolves the way the upload route resolves it: the base's own
        readers first, then the reader factory.
        """
        from agno.knowledge.reader.reader_factory import ReaderFactory

        custom = kb.get_readers()
        if reader_id:
            if reader_id in custom:
                return custom[reader_id], None
            key = reader_id.lower().strip().replace("-", "_").replace(" ", "_")
            for candidate in [key] + ([key[:-6].rstrip("_")] if key.endswith("reader") else []):
                try:
                    return ReaderFactory.create_reader(candidate), None
                except Exception:
                    continue
            return None, _error(f"Reader not found: {reader_id}", available=sorted(custom.keys()))
        if url and _is_llms_txt(url):
            from agno.knowledge.reader.llms_txt_reader import LLMsTxtReader

            configured = next((r for r in custom.values() if isinstance(r, LLMsTxtReader)), None)
            if configured is not None:
                return configured, None
            try:
                return ReaderFactory.create_reader("llms_txt"), None
            except ImportError as e:
                # Loading the llms.txt file itself is still better than refusing.
                logger.warning(f"llms.txt reader unavailable, loading the file as text: {e}")
        return None, None

    @staticmethod
    def _prepare(kb: Knowledge, content: Content, reader: Optional[Reader]) -> Content:
        # Hash before the reader is attached, as the upload route does, so the row id
        # matches a UI upload of the same source.
        content.content_hash = kb._build_content_hash(content)
        content.id = generate_id(content.content_hash)
        if reader is not None:
            content.reader = reader
        return content

    @staticmethod
    def _url_content(
        url: str, name: Optional[str], description: Optional[str], metadata: Optional[Dict[str, Any]], owner: Any
    ) -> Content:
        return Content(name=name or url, description=description, url=url, metadata=metadata, user_id=owner)

    @staticmethod
    def _text_content(
        name: str, text: str, description: Optional[str], metadata: Optional[Dict[str, Any]], owner: Any
    ) -> Content:
        return Content(
            name=name,
            description=description,
            metadata=metadata,
            file_data=FileData(content=text.encode("utf-8"), type="manual"),
            user_id=owner,
        )

    def _file_content(
        self,
        kb: Knowledge,
        file: File,
        description: Optional[str],
        metadata: Optional[Dict[str, Any]],
        owner: Any,
    ) -> Tuple[Optional[Content], Optional[Reader], Optional[str]]:
        """The content row for one attached file, or the reason it cannot be loaded.

        Bytes take the file-upload route's shape; a URL-only file takes add_url's. A file
        that only names a local path is refused: the model would be choosing server paths.
        """
        filename = _filename(file)
        extension = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
        if file.content is not None:
            if extension not in _LOADABLE_EXTENSIONS:
                return None, None, f"Unsupported file type: {extension or 'unknown'}"
            data = file.content if isinstance(file.content, bytes) else str(file.content).encode("utf-8")
            content = Content(
                name=filename,
                description=description,
                metadata=metadata,
                file_data=FileData(content=data, type=file.mime_type, filename=filename, size=len(data)),
                size=len(data),
                user_id=owner,
            )
            return self._prepare(kb, content, None), None, None
        if file.url:
            reader, err = self._resolve_reader(kb, None, file.url)
            if err:
                return None, None, json.loads(err)["error"]
            content = self._url_content(file.url, filename, description, metadata, owner)
            return self._prepare(kb, content, reader), reader, None
        return None, None, "The file has no content to load"

    @staticmethod
    def _files_result(kb: Knowledge, results: List[Dict[str, Any]], missing: List[str]) -> str:
        for name in missing:
            results.append({"filename": name, "error": "Not attached to this message"})
        loaded = sum(1 for r in results if "error" not in r)
        payload = {"knowledge_id": knowledge_base_id(kb), "files": results, "loaded": loaded}
        if loaded == 0:
            return _error("No files were loaded", **payload)
        return json.dumps({"status": "added" if loaded == len(results) else "partial", **payload}, default=str)

    def _list_bases(self) -> str:
        try:
            rows = []
            for kb_id, kb in self._bases():
                remote = not isinstance(kb, Knowledge)
                rows.append(
                    {
                        "id": kb_id,
                        "name": getattr(kb, "name", None),
                        "description": getattr(kb, "description", None),
                        "remote": remote,
                        "readers": [] if remote else sorted(kb.get_readers().keys()),
                    }
                )
            return json.dumps({"knowledge_bases": rows, "count": len(rows)}, default=str)
        except Exception as e:
            logger.exception("Failed to list knowledge bases")
            return _error(str(e))

    @staticmethod
    def _added(kb: Knowledge, content: Content, row: Optional[Content], reader: Optional[Reader]) -> str:
        result: Dict[str, Any] = {
            "knowledge_id": knowledge_base_id(kb),
            "content": _content_view(row) if row is not None else {"id": content.id, "name": content.name},
        }
        if reader is not None:
            result["reader"] = type(reader).__name__
        if result["content"].get("status") == "failed":
            return _error(result["content"].get("status_message") or "Loading failed", **result)
        return json.dumps({"status": "added", **result}, default=str)

    # ------------------------------------------------------------------
    # Sync tools
    # ------------------------------------------------------------------

    @requires_permission("knowledge", "read")
    def list_knowledge_bases(self, run_context: Optional[RunContext] = None) -> str:
        """List the knowledge bases you can manage.

        Returns:
            str: JSON with each base's id, name, description, whether it is remote, and the
            reader ids it is configured with.
        """
        return self._list_bases()

    @requires_permission("knowledge", "read")
    def list_content(
        self, knowledge: str, limit: int = 20, page: int = 1, run_context: Optional[RunContext] = None
    ) -> str:
        """List the content loaded into a knowledge base, newest first.

        Args:
            knowledge (str): The knowledge base id (or exact name) from list_knowledge_bases.
            limit (int): Rows per page, at most 100. Defaults to 20.
            page (int): 1-based page number. Defaults to 1.

        Returns:
            str: JSON with the page of content rows and the total row count.
        """
        try:
            kb, err = self._find(knowledge, sync=True)
            if err:
                return err
            limit = max(1, min(int(limit), _MAX_LIST_LIMIT))
            rows, total = kb.get_content(  # type: ignore[union-attr]
                limit=limit,
                page=max(1, int(page)),
                sort_by="created_at",
                sort_order="desc",
                user_id=self._owner(run_context),
            )
            return json.dumps({"content": [_content_view(r) for r in rows], "total": total, "page": page}, default=str)
        except Exception as e:
            logger.exception("Failed to list knowledge content")
            return _error(str(e))

    @requires_permission("knowledge", "read")
    def get_content(self, knowledge: str, content_id: str, run_context: Optional[RunContext] = None) -> str:
        """Get one content row: its status, status message and metadata.

        Args:
            knowledge (str): The knowledge base id (or exact name).
            content_id (str): The content id from list_content, add_url or add_text.

        Returns:
            str: JSON with the content row.
        """
        try:
            kb, err = self._find(knowledge, sync=True)
            if err:
                return err
            row = kb.get_content_by_id(content_id, user_id=self._owner(run_context))  # type: ignore[union-attr]
            if row is None:
                return _error(f"Content not found: {content_id}")
            return json.dumps(_content_view(row), default=str)
        except Exception as e:
            logger.exception("Failed to get knowledge content")
            return _error(str(e))

    @requires_permission("knowledge", "read")
    def search_knowledge(
        self, knowledge: str, query: str, limit: int = 5, run_context: Optional[RunContext] = None
    ) -> str:
        """Search a knowledge base the way an agent attached to it would.

        Args:
            knowledge (str): The knowledge base id (or exact name).
            query (str): The search query.
            limit (int): Maximum results, at most 20. Defaults to 5.

        Returns:
            str: JSON with each hit's name, source url and a snippet.
        """
        try:
            kb, err = self._find(knowledge)
            if err:
                return err
            docs = kb.search(  # type: ignore[union-attr]
                query, max_results=max(1, min(int(limit), _MAX_SEARCH_LIMIT)), user_id=self._owner(run_context)
            )
            results = _search_view(docs)
            return json.dumps({"results": results, "count": len(results)}, default=str)
        except Exception as e:
            logger.exception("Failed to search knowledge")
            return _error(str(e))

    @requires_permission("knowledge", "write")
    def add_url(
        self,
        knowledge: str,
        url: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        reader_id: Optional[str] = None,
        run_context: Optional[RunContext] = None,
    ) -> str:
        """Load a URL into a knowledge base and wait until it is processed.

        Handles web pages, file URLs (PDF, CSV, ...), sitemaps and llms.txt. An llms.txt URL
        uses the llms.txt reader, which loads every linked documentation page.

        Args:
            knowledge (str): The knowledge base id (or exact name).
            url (str): The URL to load.
            name (str): Display name. Defaults to the URL.
            description (str): What the content is, for people browsing the knowledge base.
            metadata (dict): Flat key/value metadata usable as search filters.
            reader_id (str): Override the reader with an id from list_knowledge_bases.

        Returns:
            str: JSON with the content row and its final status.
        """
        try:
            kb, err = self._find(knowledge, sync=True)
            if err:
                return err
            assert kb is not None
            reader, err = self._resolve_reader(kb, reader_id, url)
            if err:
                return err
            owner = self._owner(run_context)
            content = self._prepare(kb, self._url_content(url, name, description, metadata, owner), reader)
            try:
                kb._load_content(content, upsert=False, skip_if_exists=True)
            except Exception:
                # The row is already marked failed with the reason; report it below.
                logger.exception(f"Failed to load {url}")
            return self._added(kb, content, kb.get_content_by_id(content.id, user_id=owner), reader)  # type: ignore[arg-type]
        except Exception as e:
            logger.exception("Failed to add url")
            return _error(str(e))

    @requires_permission("knowledge", "write")
    def add_text(
        self,
        knowledge: str,
        name: str,
        text: str,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        run_context: Optional[RunContext] = None,
    ) -> str:
        """Store text in a knowledge base under a name and wait until it is processed.

        Args:
            knowledge (str): The knowledge base id (or exact name).
            name (str): A unique display name for this text.
            text (str): The text to store.
            description (str): What the text is.
            metadata (dict): Flat key/value metadata usable as search filters.

        Returns:
            str: JSON with the content row and its final status.
        """
        try:
            if not (name or "").strip() or not (text or "").strip():
                return _error("name and text are required")
            kb, err = self._find(knowledge, sync=True)
            if err:
                return err
            assert kb is not None
            owner = self._owner(run_context)
            content = self._prepare(kb, self._text_content(name, text, description, metadata, owner), None)
            try:
                kb._load_content(content, upsert=False, skip_if_exists=True)
            except Exception:
                logger.exception(f"Failed to load text {name}")
            return self._added(kb, content, kb.get_content_by_id(content.id, user_id=owner), None)  # type: ignore[arg-type]
        except Exception as e:
            logger.exception("Failed to add text")
            return _error(str(e))

    @requires_permission("knowledge", "write")
    def add_files(
        self,
        knowledge: str,
        filenames: Optional[List[str]] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        files: Optional[Sequence[File]] = None,
        run_context: Optional[RunContext] = None,
    ) -> str:
        """Load documents the user attached to their message into a knowledge base, and wait
        until they are processed. Supports PDF, DOCX, DOC, XLSX, XLS, PPTX, CSV, JSON, TXT, MD,
        RTF, HTML and XML. Only this message's attachments are available.

        Args:
            knowledge (str): The knowledge base id (or exact name).
            filenames (list): Attached filenames to load. Defaults to every attached file.
            description (str): What the files are, for people browsing the knowledge base.
            metadata (dict): Flat key/value metadata applied to every file, usable as search filters.

        Returns:
            str: JSON with each file's content row and final status, or its error.
        """
        try:
            if not files:
                return _error("No files are attached to this message. Ask the user to attach them and ask again.")
            kb, err = self._find(knowledge, sync=True)
            if err:
                return err
            assert kb is not None
            owner = self._owner(run_context)
            picked, missing = _pick_files(files, filenames)
            results: List[Dict[str, Any]] = []
            for file in picked:
                content, reader, reason = self._file_content(kb, file, description, metadata, owner)
                if content is None:
                    results.append({"filename": _filename(file), "error": reason})
                    continue
                try:
                    kb._load_content(content, upsert=False, skip_if_exists=True)
                except Exception:
                    logger.exception(f"Failed to load file {_filename(file)}")
                row = json.loads(self._added(kb, content, kb.get_content_by_id(content.id, user_id=owner), reader))  # type: ignore[arg-type]
                results.append({"filename": _filename(file), **{k: v for k, v in row.items() if k != "knowledge_id"}})
            return self._files_result(kb, results, missing)
        except Exception as e:
            logger.exception("Failed to add files")
            return _error(str(e))

    @requires_permission("knowledge", "delete")
    def remove_content(self, knowledge: str, content_id: str, run_context: Optional[RunContext] = None) -> str:
        """Remove a content row and its vectors from a knowledge base. This is permanent.

        Args:
            knowledge (str): The knowledge base id (or exact name).
            content_id (str): The content id to remove.

        Returns:
            str: JSON confirming removal.
        """
        try:
            kb, err = self._find(knowledge, sync=True)
            if err:
                return err
            assert kb is not None
            owner = self._owner(run_context)
            existing = kb.get_content_by_id(content_id, user_id=owner)
            if existing is None:
                return _error(f"Content not found: {content_id}")
            if owner is not None and existing.user_id is None:
                return _error("Shared content can only be removed by an admin")
            if not kb.remove_content_by_id(content_id, user_id=owner):
                return _error(f"Content could not be fully removed: {content_id}")
            return json.dumps({"status": "removed", "id": content_id, "name": existing.name})
        except Exception as e:
            logger.exception("Failed to remove knowledge content")
            return _error(str(e))

    # ------------------------------------------------------------------
    # Async tools
    # ------------------------------------------------------------------

    @requires_permission("knowledge", "read")
    async def alist_knowledge_bases(self, run_context: Optional[RunContext] = None) -> str:
        """Async variant of list_knowledge_bases."""
        return self._list_bases()

    @requires_permission("knowledge", "read")
    async def alist_content(
        self, knowledge: str, limit: int = 20, page: int = 1, run_context: Optional[RunContext] = None
    ) -> str:
        """Async variant of list_content."""
        try:
            kb, err = self._find(knowledge)
            if err:
                return err
            limit = max(1, min(int(limit), _MAX_LIST_LIMIT))
            rows, total = await kb.aget_content(  # type: ignore[union-attr]
                limit=limit,
                page=max(1, int(page)),
                sort_by="created_at",
                sort_order="desc",
                user_id=self._owner(run_context),
            )
            return json.dumps({"content": [_content_view(r) for r in rows], "total": total, "page": page}, default=str)
        except Exception as e:
            logger.exception("Failed to list knowledge content")
            return _error(str(e))

    @requires_permission("knowledge", "read")
    async def aget_content(self, knowledge: str, content_id: str, run_context: Optional[RunContext] = None) -> str:
        """Async variant of get_content."""
        try:
            kb, err = self._find(knowledge)
            if err:
                return err
            row = await kb.aget_content_by_id(content_id, user_id=self._owner(run_context))  # type: ignore[union-attr]
            if row is None:
                return _error(f"Content not found: {content_id}")
            return json.dumps(_content_view(row), default=str)
        except Exception as e:
            logger.exception("Failed to get knowledge content")
            return _error(str(e))

    @requires_permission("knowledge", "read")
    async def asearch_knowledge(
        self, knowledge: str, query: str, limit: int = 5, run_context: Optional[RunContext] = None
    ) -> str:
        """Async variant of search_knowledge."""
        try:
            kb, err = self._find(knowledge)
            if err:
                return err
            docs = await kb.asearch(  # type: ignore[union-attr]
                query, max_results=max(1, min(int(limit), _MAX_SEARCH_LIMIT)), user_id=self._owner(run_context)
            )
            results = _search_view(docs)
            return json.dumps({"results": results, "count": len(results)}, default=str)
        except Exception as e:
            logger.exception("Failed to search knowledge")
            return _error(str(e))

    @requires_permission("knowledge", "write")
    async def aadd_url(
        self,
        knowledge: str,
        url: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        reader_id: Optional[str] = None,
        run_context: Optional[RunContext] = None,
    ) -> str:
        """Async variant of add_url."""
        try:
            kb, err = self._find(knowledge)
            if err:
                return err
            assert kb is not None
            reader, err = self._resolve_reader(kb, reader_id, url)
            if err:
                return err
            owner = self._owner(run_context)
            content = self._prepare(kb, self._url_content(url, name, description, metadata, owner), reader)
            try:
                await kb._aload_content(content, upsert=False, skip_if_exists=True)
            except Exception:
                logger.exception(f"Failed to load {url}")
            row = await kb.aget_content_by_id(content.id, user_id=owner)  # type: ignore[arg-type]
            return self._added(kb, content, row, reader)
        except Exception as e:
            logger.exception("Failed to add url")
            return _error(str(e))

    @requires_permission("knowledge", "write")
    async def aadd_text(
        self,
        knowledge: str,
        name: str,
        text: str,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        run_context: Optional[RunContext] = None,
    ) -> str:
        """Async variant of add_text."""
        try:
            if not (name or "").strip() or not (text or "").strip():
                return _error("name and text are required")
            kb, err = self._find(knowledge)
            if err:
                return err
            assert kb is not None
            owner = self._owner(run_context)
            content = self._prepare(kb, self._text_content(name, text, description, metadata, owner), None)
            try:
                await kb._aload_content(content, upsert=False, skip_if_exists=True)
            except Exception:
                logger.exception(f"Failed to load text {name}")
            row = await kb.aget_content_by_id(content.id, user_id=owner)  # type: ignore[arg-type]
            return self._added(kb, content, row, None)
        except Exception as e:
            logger.exception("Failed to add text")
            return _error(str(e))

    @requires_permission("knowledge", "write")
    async def aadd_files(
        self,
        knowledge: str,
        filenames: Optional[List[str]] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        files: Optional[Sequence[File]] = None,
        run_context: Optional[RunContext] = None,
    ) -> str:
        """Async variant of add_files."""
        try:
            if not files:
                return _error("No files are attached to this message. Ask the user to attach them and ask again.")
            kb, err = self._find(knowledge)
            if err:
                return err
            assert kb is not None
            owner = self._owner(run_context)
            picked, missing = _pick_files(files, filenames)
            results: List[Dict[str, Any]] = []
            for file in picked:
                content, reader, reason = self._file_content(kb, file, description, metadata, owner)
                if content is None:
                    results.append({"filename": _filename(file), "error": reason})
                    continue
                try:
                    await kb._aload_content(content, upsert=False, skip_if_exists=True)
                except Exception:
                    logger.exception(f"Failed to load file {_filename(file)}")
                stored = await kb.aget_content_by_id(content.id, user_id=owner)  # type: ignore[arg-type]
                row = json.loads(self._added(kb, content, stored, reader))
                results.append({"filename": _filename(file), **{k: v for k, v in row.items() if k != "knowledge_id"}})
            return self._files_result(kb, results, missing)
        except Exception as e:
            logger.exception("Failed to add files")
            return _error(str(e))

    @requires_permission("knowledge", "delete")
    async def aremove_content(self, knowledge: str, content_id: str, run_context: Optional[RunContext] = None) -> str:
        """Async variant of remove_content."""
        try:
            kb, err = self._find(knowledge)
            if err:
                return err
            assert kb is not None
            owner = self._owner(run_context)
            existing = await kb.aget_content_by_id(content_id, user_id=owner)
            if existing is None:
                return _error(f"Content not found: {content_id}")
            if owner is not None and existing.user_id is None:
                return _error("Shared content can only be removed by an admin")
            if not await kb.aremove_content_by_id(content_id, user_id=owner):
                return _error(f"Content could not be fully removed: {content_id}")
            return json.dumps({"status": "removed", "id": content_id, "name": existing.name})
        except Exception as e:
            logger.exception("Failed to remove knowledge content")
            return _error(str(e))
