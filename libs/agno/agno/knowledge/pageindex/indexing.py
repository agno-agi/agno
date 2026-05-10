from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as config
from typing import Literal, Optional

from agno.knowledge.pageindex.config import PageIndexSettings
from agno.knowledge.pageindex.registry import DocumentRegistry, RegistryRecord


def _detect_doc_type(path: Path) -> Literal["pdf", "md"]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".md", ".markdown"}:
        return "md"
    raise ValueError(f"Unsupported file type: {path.suffix} ({path})")


def _build_doc_id(path: Path, tenant_id: str = "default") -> str:
    key = f"{tenant_id}:{path.resolve()}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    return f"doc_{digest}"


def _file_hash(path: Path) -> str:
    """SHA-256 of file contents (reads in 64 KB chunks)."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def index_document(
    path: str,
    settings: PageIndexSettings,
    registry: DocumentRegistry,
    doc_type: Optional[Literal["pdf", "md"]] = None,
    if_add_node_text: str = "yes",
    if_add_node_summary: str = "yes",
    if_add_doc_description: str = "no",
) -> RegistryRecord:
    """Index a PDF or Markdown file and register it.

    If a document with identical content (by SHA-256) is already indexed,
    returns the existing record without re-indexing.
    """
    src = Path(path).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(f"Document not found: {src}")

    content_hash = _file_hash(src)
    existing = registry.find_by_hash(content_hash)
    if existing is not None:
        return existing

    actual_type = doc_type or _detect_doc_type(src)
    output_dir = settings.tenant_results_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{src.stem}_structure.json"
    doc_id = _build_doc_id(src, settings.tenant_id)

    if actual_type == "pdf":
        from agno.knowledge.pageindex._core.page_index import page_index_main

        opt = config(
            model=settings.active_model,
            toc_check_page_num=20,
            max_page_num_each_node=10,
            max_token_num_each_node=20000,
            if_add_node_id="yes",
            if_add_node_summary=if_add_node_summary,
            if_add_doc_description=if_add_doc_description,
            if_add_node_text=if_add_node_text,
        )
        structure = page_index_main(str(src), opt)
    else:
        from agno.knowledge.pageindex._core.page_index_md import md_to_tree
        from agno.knowledge.pageindex._core.utils import ConfigLoader

        loader = ConfigLoader()
        opt = loader.load(
            {
                "model": settings.active_model,
                "if_add_node_summary": if_add_node_summary,
                "if_add_doc_description": if_add_doc_description,
                "if_add_node_text": if_add_node_text,
                "if_add_node_id": "yes",
            }
        )
        structure = asyncio.run(
            md_to_tree(
                md_path=str(src),
                if_thinning=False,
                min_token_threshold=5000,
                if_add_node_summary=opt.if_add_node_summary,
                summary_token_threshold=200,
                model=opt.model,
                if_add_doc_description=opt.if_add_doc_description,
                if_add_node_text=opt.if_add_node_text,
                if_add_node_id=opt.if_add_node_id,
            )
        )

    with output_file.open("w", encoding="utf-8") as fh:
        json.dump(structure, fh, indent=2, ensure_ascii=False)

    record = RegistryRecord(
        doc_id=doc_id,
        doc_name=structure.get("doc_name", src.name),
        doc_type=actual_type,
        source_path=str(src),
        structure_path=str(output_file.resolve()),
        indexed_at=DocumentRegistry.now_iso(),
        content_hash=content_hash,
    )
    registry.upsert(record)
    return record


def index_from_bytes(
    filename: str,
    content: bytes,
    settings: PageIndexSettings,
    registry: DocumentRegistry,
    **index_kwargs,
) -> RegistryRecord:
    """Save uploaded bytes to the tenant upload directory, then index.

    Returns the existing record without re-indexing if identical content
    has already been indexed.
    """
    content_hash = hashlib.sha256(content).hexdigest()
    existing = registry.find_by_hash(content_hash)
    if existing is not None:
        return existing

    upload_dir = settings.tenant_upload_dir
    upload_dir.mkdir(parents=True, exist_ok=True)

    dest = upload_dir / filename
    if dest.exists():
        stem = dest.stem
        suffix = dest.suffix
        short_hash = hashlib.sha1(content[:4096]).hexdigest()[:8]
        dest = upload_dir / f"{stem}_{short_hash}{suffix}"

    dest.write_bytes(content)
    return index_document(
        path=str(dest),
        settings=settings,
        registry=registry,
        **index_kwargs,
    )


def list_candidate_files(directory: str, glob_pattern: str) -> list[Path]:
    """List files in *directory* matching *glob_pattern*."""
    base = Path(directory).expanduser().resolve()
    if not base.exists() or not base.is_dir():
        raise NotADirectoryError(f"Invalid directory: {base}")
    return sorted(p for p in base.glob(glob_pattern) if p.is_file())
