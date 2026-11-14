"""Read configured Sources with existing providers and readers."""

import asyncio
import io
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from agno.db.schemas.sources import validate_source_fields
from agno.knowledge.document import Document
from agno.utils.string import hash_string_sha256


def is_remote_git(source: Dict[str, Any]) -> bool:
    """Git URL Sources support sandbox checkout only; the reader rejects them."""
    return source["type"] == "git" and source["reference"].startswith("https://")


def _local_files(source: Dict[str, Any], paths: Optional[List[str]] = None, pattern: Optional[str] = None):
    from fnmatch import fnmatch

    from agno.context.mode import ContextMode
    from agno.context.workspace import WorkspaceContextProvider

    if is_remote_git(source):
        raise ValueError("Git URL Sources are for sandbox checkout and publication; HTTP reading is not supported")
    root = Path(source["reference"]).expanduser().resolve()
    if not root.exists():
        raise ValueError("Source root is unavailable")
    provider = WorkspaceContextProvider(root=root if root.is_dir() else root.parent, mode=ContextMode.tools)
    if not provider.status().ok:
        raise ValueError("Source root is unavailable")
    workspace = provider.get_tools()[0]
    configured = (source.get("config") or {}).get("paths")

    def confined(path):
        error, resolved = workspace._resolve(path)
        if error:
            raise ValueError("Source read failed: " + error)
        if root.is_file() and resolved != root:
            raise ValueError("Source selection must stay within the configured file")
        return resolved.relative_to(provider.root).as_posix()

    allowed = {(provider.root / path).resolve() for path in configured} if configured else None
    explicit = paths is not None or bool(configured) or root.is_file()
    if paths is not None:
        if not paths:
            raise ValueError("Source selection cannot be empty")
        selected = {confined(path) for path in paths}
        if allowed is not None and not {(provider.root / path).resolve() for path in selected} <= allowed:
            raise ValueError("Source selection is outside configured paths")
        if not configured and root.is_dir() and source["type"] == "markdown":
            if any(not path.endswith((".md", ".markdown")) for path in selected):
                raise ValueError("Source selection must contain Markdown files")
    elif configured:
        selected = {confined(path) for path in configured}
    elif root.is_file():
        selected = {confined(root.name)}
    else:
        # Workspace owns discovery, exclusions and confinement. Discovery never reads content.
        listing = workspace._list_files(".", pattern, True, 100)
        if listing.startswith("Error"):
            raise ValueError("Source listing failed")
        selected = {
            entry["path"]
            for entry in json.loads(listing)["files"]
            if entry["type"] == "file" and (source["type"] == "git" or entry["path"].endswith((".md", ".markdown")))
        }
    return (
        provider,
        workspace,
        sorted(path for path in selected if not pattern or fnmatch(Path(path).name, pattern)),
        explicit,
    )


def _paths_for_links(source: Dict[str, Any], links: List[str]) -> Optional[List[str]]:
    from urllib.parse import unquote, urlparse

    if not links:
        raise ValueError("Proposal evidence requires selected links")
    if source["type"] == "website":
        if set(links) != {source["reference"]}:
            raise ValueError("Proposal evidence must link to the configured page")
        return None
    if is_remote_git(source):
        raise ValueError("Git URL Sources are for sandbox checkout and publication; HTTP reading is not supported")
    root = Path(source["reference"]).expanduser().resolve()
    if not root.exists():
        raise ValueError("Source root is unavailable")
    base = root if root.is_dir() else root.parent
    paths = []
    for link in links:
        parsed = urlparse(link)
        if parsed.scheme != "file" or parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("Proposal evidence must link to files in this Source")
        try:
            paths.append(Path(unquote(parsed.path)).relative_to(base).as_posix())
        except ValueError as exc:
            raise ValueError("Proposal evidence must link to files in this Source") from exc
    return paths


def browse_source(
    source: Dict[str, Any],
    run_id: str,
    path: Optional[str] = None,
    pattern: Optional[str] = None,
    offset: int = 0,
    limit: int = 20,
    content_offset: int = 0,
    max_chars: int = 8000,
) -> Dict[str, Any]:
    """Page a confined index, or read a bounded fragment of one selected document."""
    validate_source_fields(
        {
            **{key: source.get(key) for key in ("type", "reference", "credential_ref")},
            "config": {key: value for key, value in (source.get("config") or {}).items() if key != "metadata"},
        }
    )
    if not run_id or offset < 0 or content_offset < 0 or not 1 <= limit <= 100 or not 1 <= max_chars <= 16000:
        raise ValueError("Source paging requires a run id, nonnegative offsets, limit 1..100 and max_chars 1..16000")
    path = path or None
    pattern = pattern or None
    if path is None:
        if source["type"] == "website":
            entries = [{"path": source["reference"], "link": source["reference"]}]
        else:
            provider, _, paths, _ = _local_files(source, pattern=pattern)
            entries = [{"path": item, "link": (provider.root / item).as_uri()} for item in paths]
        page: Dict[str, Any] = {"data": [], "total_count": len(entries), "next_offset": None}
        for entry in entries[offset : offset + limit]:
            candidate = {**page, "data": [*page["data"], entry], "next_offset": offset + len(page["data"]) + 1}
            if len(json.dumps(candidate).encode()) > 65536:
                break
            page = candidate
        if offset < len(entries) and not page["data"]:
            raise ValueError("Source index entry exceeds the response limit")
        if offset + len(page["data"]) >= len(entries):
            page["next_offset"] = None
        return page
    if source["type"] == "website":
        if path != source["reference"]:
            raise ValueError("Source selection must match the configured page")
        documents = read_source(source, run_id)
    else:
        documents = read_source(source, run_id, paths=[path])
    if len(documents) != 1:
        raise ValueError("Select exactly one Source document")
    item = {key: value for key, value in documents[0].items() if key != "skipped_paths"}
    content = item.pop("content")
    if content_offset > len(content):
        raise ValueError("Source content offset is beyond the document")
    item.update(path=path, content_offset=content_offset, content_length=len(content))

    def fragment(length):
        end = content_offset + length
        return {
            **item,
            "content": content[content_offset:end],
            "next_content_offset": end if end < len(content) else None,
        }

    low, high = 0, min(max_chars, len(content) - content_offset)
    while low < high:
        middle = (low + high + 1) // 2
        if len(json.dumps(fragment(middle)).encode()) <= 65536:
            low = middle
        else:
            high = middle - 1
    result = fragment(low)
    if len(json.dumps(result).encode()) > 65536 or (low == 0 and content_offset < len(content)):
        raise ValueError("Source evidence metadata exceeds the response limit")
    return result


async def abrowse_source(
    source: Dict[str, Any],
    run_id: str,
    path: Optional[str] = None,
    pattern: Optional[str] = None,
    offset: int = 0,
    limit: int = 20,
    content_offset: int = 0,
    max_chars: int = 8000,
) -> Dict[str, Any]:
    """Offload confined discovery and selected reads without blocking the event loop."""
    return await asyncio.to_thread(
        browse_source, source, run_id, path, pattern, offset, limit, content_offset, max_chars
    )


def _documents(source: Dict[str, Any], paths: Optional[List[str]] = None) -> List[Document]:
    validate_source_fields(
        {
            **{key: source.get(key) for key in ("type", "reference", "credential_ref")},
            "config": {key: value for key, value in (source.get("config") or {}).items() if key != "metadata"},
        }
    )
    reference = source["reference"]
    if source["type"] == "website":
        from agno.knowledge.reader.website_reader import WebsiteReader

        return WebsiteReader(chunk=False, max_depth=0, max_links=1, public_only=True).read(reference)
    from agno.knowledge.reader.markdown_reader import MarkdownReader

    provider, workspace, paths, explicit = _local_files(source, paths=paths)
    skipped = []
    documents = []
    reader = MarkdownReader(chunk=False)
    for path in sorted(paths):
        content = workspace._read_file(path, None, None, "utf-8")
        if content.startswith("Error"):
            if not explicit and ("file too long" in content or "codec can't decode" in content):
                skipped.append(path)
                continue
            raise ValueError("Source read failed")
        # Workspace owns path confinement and exclusions. Remove only its display line numbers.
        content = "\n".join(line.split("\t", 1)[1] for line in content.split("\n") if "\t" in line)
        link = (provider.root / path).as_uri()
        if source["type"] == "markdown":
            loaded = reader.read(io.StringIO(content), name=path)
        else:
            loaded = [Document(name=path, content=content)]
        if not loaded:
            raise ValueError("Source reader returned no documents")
        for document in loaded:
            document.meta_data["url"] = link
        documents.extend(loaded)
    for document in documents:
        document.meta_data["skipped_paths"] = skipped
    return documents


def read_source(
    source: Dict[str, Any], run_id: str, paths: Optional[List[str]] = None, links: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """Return evidence only after every selected document was read successfully."""
    if not run_id:
        raise ValueError("Source evidence requires a run id")
    if links is not None:
        paths = _paths_for_links(source, links)
    documents = _documents(source, paths=paths)
    if not documents:
        raise ValueError("Source reader returned no documents")
    return [
        {
            "source_id": source["id"],
            "run_id": run_id,
            "content_hash": hash_string_sha256(document.content),
            "link": document.meta_data.get("url") or source["reference"],
            "content": document.content,
            "skipped_paths": document.meta_data.get("skipped_paths", []),
        }
        for document in documents
    ]


async def aread_source(
    source: Dict[str, Any], run_id: str, paths: Optional[List[str]] = None, links: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """Offload file/provider reads; native database calls remain async in the manager."""
    return await asyncio.to_thread(read_source, source, run_id, paths, links)


def _proposal_fields(source_id: str, proposal: Any, evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
    from agno.company.declarations import IntakeProposal

    proposal = IntakeProposal.model_validate(proposal)
    links = set(proposal.evidence_links)
    selected = [item for item in evidence if item["link"] in links]
    if {item["link"] for item in selected} != links:
        raise ValueError("Proposal evidence must link to documents read from this Source")
    if set(proposal.evidence_hashes) != links:
        raise ValueError("Proposal evidence requires an observed content hash for every selected link")
    if any(proposal.evidence_hashes[item["link"]] != item["content_hash"] for item in selected):
        raise ValueError("Proposal evidence changed; read the Source again before proposing work")
    # A stable issue identity survives edits to the evidence or proposal wording.
    # The database enforces uniqueness within the Product, including completed Tasks.
    return {
        "title": proposal.title,
        "brief": proposal.brief,
        "dedupe_key": hash_string_sha256(json.dumps([source_id, proposal.proposal_key])),
        "evidence": [{k: v for k, v in item.items() if k != "content"} for item in selected],
    }
