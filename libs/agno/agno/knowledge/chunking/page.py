"""
Docs Chunking
=============

A heading-aware markdown chunker and reader.

MarkdownChunking depends on `unstructured` (a very large dependency tree) and
its base strategy collapses whitespace, which flattens code examples onto one
line. This chunker keeps newlines exactly as written.

Rules:
- Split on H1/H2 headings; deeper headings stay with their section.
- A section that holds nothing but headings (a title followed straight by its
  first H2) is folded into the next section, so no chunk is a bare heading;
  a page that is only a title yields no chunks at all.
- A section longer than CHUNK_SIZE is split on paragraph boundaries (and, as a
  last resort, on lines), never mid-line. A fenced code block longer than
  CHUNK_SIZE is split on lines too, with the fence closed and re-opened in
  each piece, so every chunk is valid markdown and fits the embedding limit.
- Every chunk starts with the page's context line — "Page title: its first
  paragraph" — and a breadcrumb line — "Page title › Section" — so the
  embedding of a section carries what the page is about and the agent sees
  where a chunk lives. (A section of an overview page is often a list of
  links; without the context line it never matches the question the page
  answers.) The fumadocs site's `# Title (/docs/path)` and `## Heading
  [#anchor]` suffixes are stripped from breadcrumbs (chunk bodies keep the raw
  lines).
- Chunk metadata carries the breadcrumb, the page's top-level `section`
  (`agents`, `examples`, ...) and its `kind`: `example` (under /examples or a
  usage/ folder), `reference` (/reference, /reference-api) or `guide`.
"""

from __future__ import annotations

import re

from agno.knowledge.chunking.strategy import ChunkingStrategy
from agno.knowledge.document.base import Document

DEFAULT_CHUNK_SIZE = 2000
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
ANCHOR_SUFFIX = re.compile(r"\s*\[#[^\]]*\]\s*$")  # fumadocs '## Heading [#anchor]'
TITLE_PATH_SUFFIX = re.compile(r"\s*\(/[^)\s]*\)\s*$")  # fumadocs '# Title (/docs/path)'

# (delimiter character, opening length, complete opening line). A closing fence
# must use the same character and at least the opening length; shorter runs are
# literal content, which is why four-backtick blocks can safely show ``` fences.
FenceState = tuple[str, int, str]


def _fence_step(line: str, opened: FenceState | None) -> tuple[FenceState | None, bool]:
    """Advance fenced-code state and say whether `line` opened or closed it."""
    match = FENCE.match(line)
    if match is None:
        return opened, False
    delimiter, suffix = match.groups()
    if opened is None:
        # Backticks are forbidden in a backtick fence's info string. Treat such
        # a line as prose instead of opening a fence that can never close.
        if delimiter[0] == "`" and "`" in suffix:
            return None, False
        return (delimiter[0], len(delimiter), line), True
    character, length, _ = opened
    if delimiter[0] == character and len(delimiter) >= length and not suffix.strip():
        return None, True
    return opened, False


def clean_heading(title: str, page_title: bool = False) -> str:
    """Heading text for breadcrumbs and titles, without the site's anchor/path suffixes."""
    title = ANCHOR_SUFFIX.sub("", title)
    if page_title:
        title = TITLE_PATH_SUFFIX.sub("", title)
    return title.strip()


def _heading_only(body: str) -> bool:
    return all(HEADING.match(line) for line in body.splitlines() if line.strip())


def page_intro(text: str, limit: int = 300) -> str:
    """The page's first paragraph of prose (what sits under the title), at most `limit` chars."""
    lines: list[str] = []
    fence: FenceState | None = None
    for line in text.splitlines():
        stripped = line.strip()
        fence, _ = _fence_step(line, fence)
        if fence is not None or not stripped or stripped.startswith(("#", "```", "~~~", "**Step")):
            if lines:
                break
            continue
        lines.append(stripped.lstrip("> ").strip())  # a callout's quote marker adds nothing
    return " ".join(lines)[:limit]


def _sections(text: str, split_level: int) -> list[tuple[list[str], str]]:
    """[(heading_trail, body)] splitting on headings of level <= split_level, outside code fences.

    A section with nothing but headings is folded into the next section (or, at the end of the
    page, into the previous one), so a chunk is never a bare title. A page of headings only
    yields no sections.
    """
    trail: list[str] = []
    sections: list[tuple[list[str], list[str]]] = [([], [])]
    fence: FenceState | None = None
    for line in text.splitlines():
        fence, _ = _fence_step(line, fence)
        match = None if fence is not None else HEADING.match(line)
        if match and len(match.group(1)) <= split_level:
            level = len(match.group(1))
            title = clean_heading(match.group(2), page_title=level == 1)
            trail = trail[: level - 1] + [title]
            sections.append((list(trail), [line]))
            continue
        sections[-1][1].append(line)
    folded: list[tuple[list[str], str]] = []
    pending = ""
    for section_trail, lines in sections:
        body = "\n".join(lines).strip("\n")
        if not body.strip():
            continue
        if _heading_only(body):
            pending = f"{pending}\n\n{body}" if pending else body
            continue
        folded.append((section_trail, f"{pending}\n\n{body}" if pending else body))
        pending = ""
    if pending and folded:
        last_trail, last_body = folded[-1]
        folded[-1] = (last_trail, f"{last_body}\n\n{pending}")
    return folded


def page_kind(path: str) -> str:
    """`example` for /examples/* and usage/ pages, `reference` for the API reference, else `guide`."""
    parts = path.strip("/").split("/")
    if parts[0] in ("reference", "reference-api"):
        return "reference"
    if parts[0] == "examples" or "usage" in parts:
        return "example"
    return "guide"


def _split_long(body: str, limit: int) -> list[str]:
    """Split on blank lines, then on lines. A fence longer than the limit is split on lines
    too; each continuation piece closes and re-opens the fence so every chunk is valid markdown.
    A short remaining tail (under a quarter of the limit) is never split off: it stays with the
    piece before it, so a piece may run up to limit + limit // 4 plus one line."""
    if len(body) <= limit:
        return [body]
    pieces: list[str] = []
    current: list[str] = []
    fence: FenceState | None = None
    size = 0
    total, consumed = len(body), 0

    def flush(reopen: bool) -> None:
        nonlocal current, size
        if current:
            text = "\n".join(current).strip("\n")
            if fence is not None and reopen:
                text += "\n" + fence[0] * fence[1]
            pieces.append(text)
        current, size = [], 0
        if fence is not None and reopen:
            current.append(fence[2])
            size = len(fence[2]) + 1

    for line in body.splitlines():
        tail_left = total - consumed > limit // 4  # this line and everything after it
        consumed += len(line) + 1
        was_open = fence is not None
        fence, is_delimiter = _fence_step(line, fence)
        if is_delimiter:
            if was_open and fence is None:  # the closing fence stays with its block
                current.append(line)
                size += len(line) + 1
                continue
        if fence is None and not line.strip() and size >= limit // 2 and tail_left:
            flush(reopen=False)
            continue
        if size + len(line) + 1 > limit and current and tail_left:
            flush(reopen=fence is not None and not is_delimiter)
        current.append(line)
        size += len(line) + 1
    flush(reopen=False)
    return [p for p in pieces if p.strip()] or [body]


class PageMarkdownChunking(ChunkingStrategy):
    """Heading-aware chunks that keep newlines and code fences intact."""

    def __init__(self, chunk_size: int = DEFAULT_CHUNK_SIZE, split_level: int = 2):
        self.chunk_size = chunk_size
        self.split_level = split_level

    def chunk_pairs(self, text: str) -> list[tuple[str, str]]:
        """[(breadcrumb, chunk_text)]; the chunk opens with the page context line, then the breadcrumb."""
        chunks: list[tuple[str, str]] = []
        sections = _sections(text, self.split_level)
        page_title = next((trail[0] for trail, _ in sections if trail), "")
        intro = page_intro(text)
        context = (
            "" if not intro else intro if not page_title or intro.startswith(page_title) else f"{page_title}: {intro}"
        )
        for trail, body in sections:
            crumbs = [page_title] + [t for t in trail if t != page_title] if page_title else trail
            breadcrumb = " › ".join(c for c in crumbs if c)
            for piece in _split_long(body, self.chunk_size):
                chunk = f"{breadcrumb}\n\n{piece}" if breadcrumb and not piece.startswith(breadcrumb) else piece
                chunks.append((breadcrumb, f"{context}\n\n{chunk}" if context else chunk))
        return chunks

    def chunk_texts(self, text: str) -> list[str]:
        return [chunk for _, chunk in self.chunk_pairs(text)]

    def chunk(self, document: Document) -> list[Document]:
        meta_data = document.meta_data or {}
        path = str(meta_data.get("path") or document.name or "")
        documents = []
        for index, (breadcrumb, text) in enumerate(self.chunk_pairs(document.content or ""), start=1):
            meta = dict(meta_data)
            meta["chunk"] = index
            meta["chunk_size"] = len(text)
            meta["breadcrumb"] = breadcrumb
            if path:
                meta["section"] = path.strip("/").split("/")[0]
                meta["kind"] = page_kind(path)
            documents.append(
                Document(
                    id=self._generate_chunk_id(document, index, content=text),
                    name=document.name,
                    content=text,
                    meta_data=meta,
                    content_id=document.content_id,
                )
            )
        return documents
