from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from agno.knowledge.pageindex.config import PageIndexSettings
from agno.knowledge.pageindex.registry import RegistryRecord
from agno.knowledge.pageindex.schemas import RetrievalResult

# -- structure cache -----------------------------------------------------------

_structure_cache: Dict[str, dict] = {}
_structure_cache_lock = threading.Lock()
_STRUCTURE_CACHE_MAX = 256


STOP_WORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "to",
    "of",
    "in",
    "on",
    "for",
    "with",
    "is",
    "are",
    "be",
    "this",
    "that",
    "it",
    "as",
    "by",
    "from",
    "show",
    "shown",
    "give",
    "explain",
    "summarize",
}


@dataclass
class _RankedNode:
    title: str
    summary: str
    start_index: int
    end_index: int
    node_id: str
    score: int
    matched_terms: int
    total_terms: int


# -- helpers -------------------------------------------------------------------


def _load_structure(structure_path: str) -> dict:
    with _structure_cache_lock:
        cached = _structure_cache.get(structure_path)
        if cached is not None:
            return cached
    with Path(structure_path).open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    with _structure_cache_lock:
        if len(_structure_cache) >= _STRUCTURE_CACHE_MAX:
            oldest = next(iter(_structure_cache))
            del _structure_cache[oldest]
        _structure_cache[structure_path] = data
    return data


def invalidate_structure_cache(structure_path: str = "") -> None:
    """Remove one or all entries from the structure cache."""
    with _structure_cache_lock:
        if structure_path:
            _structure_cache.pop(structure_path, None)
        else:
            _structure_cache.clear()


def _flatten_nodes(nodes: list[dict], output: list[dict]) -> None:
    for node in nodes:
        output.append(node)
        if node.get("nodes"):
            _flatten_nodes(node["nodes"], output)


def _rank_nodes(query: str, structure: dict, top_k: int) -> list[_RankedNode]:
    all_nodes: list[dict] = []
    _flatten_nodes(structure.get("structure", []), all_nodes)

    raw_terms = re.findall(r"[a-zA-Z0-9_]+", query.lower())
    terms = [t for t in raw_terms if len(t) > 1 and t not in STOP_WORDS]
    query_phrase = " ".join(terms)

    ranked: list[_RankedNode] = []
    for node in all_nodes:
        title = str(node.get("title", ""))
        summary = str(node.get("summary", ""))
        title_l = title.lower()
        summary_l = summary.lower()
        score = 0
        matched = 0
        for term in terms:
            if term in title_l:
                score += 3
                matched += 1
            elif term in summary_l:
                score += 1
                matched += 1
        if query_phrase and query_phrase in f"{title_l} {summary_l}":
            score += 4
        if score <= 0:
            continue
        ranked.append(
            _RankedNode(
                title=title,
                summary=summary,
                start_index=int(node.get("start_index", 1) or 1),
                end_index=int(node.get("end_index", node.get("start_index", 1)) or 1),
                node_id=str(node.get("node_id", "")),
                score=score,
                matched_terms=matched,
                total_terms=len(terms),
            )
        )

    ranked.sort(key=lambda r: r.score, reverse=True)
    return ranked[:top_k]


def _extract_pdf_text(source_path: str, start_index: int, end_index: int) -> str:
    try:
        import pymupdf
    except ImportError:
        raise ImportError("`pymupdf` not installed. Please install using `pip install pymupdf`")

    start = max(start_index - 1, 0)
    end = max(end_index - 1, start)
    pages: list[str] = []
    with pymupdf.open(source_path) as doc:
        max_page = doc.page_count - 1
        for idx in range(start, min(end, max_page) + 1):
            pages.append(doc[idx].get_text())
    return "\n".join(pages).strip()


def _extract_md_text(source_path: str, max_chars: int) -> str:
    with Path(source_path).open("r", encoding="utf-8") as fh:
        return fh.read()[:max_chars]


# -- public API ----------------------------------------------------------------


def retrieve(
    query: str,
    record: RegistryRecord,
    settings: PageIndexSettings,
    top_k: Optional[int] = None,
) -> list[RetrievalResult]:
    """Rank nodes against *query* and return evidence snippets."""
    effective_k = top_k or settings.top_k_nodes
    structure = _load_structure(record.structure_path)
    ranked = _rank_nodes(query, structure, effective_k)
    ranked = [n for n in ranked if n.score >= settings.min_retrieval_score]

    results: list[RetrievalResult] = []
    for node in ranked:
        if record.doc_type == "pdf":
            evidence = _extract_pdf_text(record.source_path, node.start_index, node.end_index)
        else:
            evidence = _extract_md_text(record.source_path, settings.max_evidence_chars)

        if not evidence:
            evidence = node.summary

        results.append(
            RetrievalResult(
                content=evidence[: settings.max_evidence_chars],
                title=node.title,
                node_id=node.node_id,
                start_index=node.start_index,
                end_index=node.end_index,
                score=node.score,
                term_coverage=node.matched_terms / node.total_terms if node.total_terms else 0.0,
                source_path=record.source_path,
            )
        )

    if not results:
        results.append(
            RetrievalResult(
                content="INSUFFICIENT_EVIDENCE: no strongly relevant nodes found for this query.",
                source_path=record.source_path,
                insufficient_evidence=True,
            )
        )
    return results


def score_doc_relevance(query: str, record: RegistryRecord) -> int:
    """Score a single document's relevance to *query* using its structure.

    Returns the sum of the top-3 node scores.
    """
    try:
        structure = _load_structure(record.structure_path)
    except Exception:
        return 0
    ranked = _rank_nodes(query, structure, top_k=3)
    return sum(n.score for n in ranked)


def retrieve_multi(
    query: str,
    records: list[RegistryRecord],
    settings: PageIndexSettings,
    max_docs: int = 3,
    top_k: Optional[int] = None,
) -> list[RetrievalResult]:
    """Retrieve across multiple documents.

    Scores every doc by keyword-matching, picks the top *max_docs*,
    retrieves from each, and merges results sorted by score.
    """
    scored = [(score_doc_relevance(query, rec), rec) for rec in records]
    scored.sort(key=lambda x: x[0], reverse=True)
    top_docs = [(s, rec) for s, rec in scored[:max_docs] if s > 0]

    if not top_docs:
        return [
            RetrievalResult(
                content="INSUFFICIENT_EVIDENCE: no relevant documents found for this query.",
                insufficient_evidence=True,
            )
        ]

    all_results: list[RetrievalResult] = []
    for _, rec in top_docs:
        results = retrieve(query, rec, settings, top_k=top_k)
        for r in results:
            if not r.insufficient_evidence:
                r.doc_id = rec.doc_id
                r.doc_name = rec.doc_name
                all_results.append(r)

    if not all_results:
        return [
            RetrievalResult(
                content="INSUFFICIENT_EVIDENCE: no strongly relevant nodes found across documents.",
                insufficient_evidence=True,
            )
        ]

    all_results.sort(key=lambda r: r.score, reverse=True)
    return all_results
