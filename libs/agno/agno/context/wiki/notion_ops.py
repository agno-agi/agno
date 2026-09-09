"""
Notion conversion helpers for the WikiContextProvider NotionDatabaseBackend.
===========================================================================

Pure functions: block <-> markdown conversion, frontmatter parsing,
slugify, manifest IO. No Notion API calls live here -- those stay in
``backend.py`` so the conversion logic is unit-testable without a
network round-trip.

Supported block types (round-trip both directions):
    paragraph, heading_1, heading_2, heading_3,
    bulleted_list_item, numbered_list_item, to_do,
    quote, code, divider.

Supported inline annotations:
    bold, italic, code, link.

Unsupported blocks (toggle, callout, table, image, embed, child_page,
child_database, synced_block, column_list) are rendered as an HTML
comment placeholder when reading from Notion and are never produced
when writing back. That keeps the round-trip a no-op for documents
written through the agent surface; documents authored in Notion's UI
with unsupported blocks survive a sync (as placeholders) and stay
intact through a write that doesn't touch them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Frontmatter + manifest
# ---------------------------------------------------------------------------


@dataclass
class Frontmatter:
    """Parsed page frontmatter. ``notion_page_id`` is empty for new files."""

    notion_page_id: str | None
    notion_last_edited: str | None
    title: str


@dataclass
class Manifest:
    """``{filename: page_id}`` captured at last sync.

    Persisted as ``.notion-sync.json`` at the wiki dir root. ``commit_after_write``
    compares the current set of files against this snapshot to detect locally
    deleted pages (which become Notion archives).
    """

    entries: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> Manifest:
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return cls()
        return cls(entries=dict(data.get("entries", {})))

    def save(self, path: Path) -> None:
        path.write_text(
            json.dumps({"entries": self.entries}, indent=2, sort_keys=True),
            encoding="utf-8",
        )


_FRONTMATTER_KEYS = ("notion_page_id", "notion_last_edited", "title")


def render_page_file(
    *,
    title: str,
    page_id: str | None,
    last_edited: str | None,
    body: str,
) -> str:
    """Serialize a page as ``---`` frontmatter + markdown body."""
    lines = ["---"]
    if page_id:
        lines.append(f"notion_page_id: {page_id}")
    if last_edited:
        lines.append(f"notion_last_edited: {last_edited}")
    lines.append(f"title: {title}")
    lines.append("---")
    return "\n".join(lines) + "\n\n" + body.rstrip() + "\n"


def parse_page_file(text: str) -> tuple[Frontmatter, str]:
    """Return ``(frontmatter, body)``. Missing frontmatter yields blanks."""
    empty = Frontmatter(notion_page_id=None, notion_last_edited=None, title="")
    if not text.startswith("---\n"):
        return empty, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return empty, text
    header = text[4:end]
    body = text[end + 5 :]
    fm: dict[str, str | None] = {key: None for key in _FRONTMATTER_KEYS}
    for line in header.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        if key in _FRONTMATTER_KEYS:
            fm[key] = val.strip()
    return (
        Frontmatter(
            notion_page_id=fm["notion_page_id"] or None,
            notion_last_edited=fm["notion_last_edited"] or None,
            title=fm["title"] or "",
        ),
        body,
    )


# ---------------------------------------------------------------------------
# Slug / filename
# ---------------------------------------------------------------------------


_SLUG_MAX_LEN = 60


def slugify(title: str) -> str:
    """ASCII kebab-case slug, max 60 chars. Empty input becomes ``untitled``."""
    out = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    out = out[:_SLUG_MAX_LEN].rstrip("-")
    return out or "untitled"


def page_filename(title: str, page_id: str, *, used: set[str] | None = None) -> str:
    """``<slug>.md``, with a stable id suffix if two pages slug to the same name."""
    base = slugify(title)
    name = f"{base}.md"
    if used is not None and name in used:
        suffix = page_id.replace("-", "")[:6]
        name = f"{base}-{suffix}.md"
    return name


# ---------------------------------------------------------------------------
# Notion blocks -> markdown
# ---------------------------------------------------------------------------


_BLOCK_TO_MARKDOWN_HANDLERS: dict[str, str] = {
    "paragraph": "paragraph",
    "heading_1": "heading",
    "heading_2": "heading",
    "heading_3": "heading",
    "bulleted_list_item": "bulleted",
    "numbered_list_item": "numbered",
    "to_do": "todo",
    "quote": "quote",
    "code": "code",
    "divider": "divider",
}


_LIST_BLOCK_TYPES = {"bulleted_list_item", "numbered_list_item", "to_do"}


def blocks_to_markdown(blocks: list[dict[str, Any]]) -> str:
    """Convert a flat list of Notion blocks to markdown.

    Children of toggles/callouts are not recursed -- v1 is flat. Unsupported
    block types render as a one-line HTML comment so the file isn't silently
    lossy and so a subsequent commit doesn't lose them (the comment is a
    no-op block when parsed back).

    Consecutive list items of the same type are joined with a single
    newline so markdown parsers treat them as one list. Everything else
    is separated by a blank line.
    """
    rendered: list[tuple[str, str]] = []  # (block_type, markdown)
    numbered_counter = 0
    for block in blocks:
        btype = block.get("type", "")
        handler = _BLOCK_TO_MARKDOWN_HANDLERS.get(btype)
        if btype != "numbered_list_item":
            numbered_counter = 0

        if handler == "paragraph":
            text = _rich_text_to_md(block["paragraph"]["rich_text"])
        elif handler == "heading":
            level = int(btype[-1])
            hashes = "#" * level
            text = f"{hashes} {_rich_text_to_md(block[btype]['rich_text'])}"
        elif handler == "bulleted":
            text = f"- {_rich_text_to_md(block['bulleted_list_item']['rich_text'])}"
        elif handler == "numbered":
            numbered_counter += 1
            text = f"{numbered_counter}. {_rich_text_to_md(block['numbered_list_item']['rich_text'])}"
        elif handler == "todo":
            checked = block["to_do"].get("checked", False)
            marker = "[x]" if checked else "[ ]"
            text = f"- {marker} {_rich_text_to_md(block['to_do']['rich_text'])}"
        elif handler == "quote":
            quoted = _rich_text_to_md(block["quote"]["rich_text"])
            text = "\n".join(f"> {line}" for line in (quoted.splitlines() or [""]))
        elif handler == "code":
            lang = block["code"].get("language", "") or ""
            content = _rich_text_to_md(block["code"]["rich_text"])
            fence_lang = lang if lang and lang != "plain text" else ""
            text = f"```{fence_lang}\n{content}\n```"
        elif handler == "divider":
            text = "---"
        else:
            text = f"<!-- skipped unsupported block: {btype} -->"
        rendered.append((btype, text))

    pieces: list[str] = []
    for i, (btype, text) in enumerate(rendered):
        if i == 0:
            pieces.append(text)
            continue
        prev_type = rendered[i - 1][0]
        # Consecutive list items of the *same* type collapse onto contiguous
        # lines so a markdown parser keeps them in one list.
        if btype in _LIST_BLOCK_TYPES and prev_type == btype:
            pieces.append("\n")
        else:
            pieces.append("\n\n")
        pieces.append(text)
    return "".join(pieces).strip()


def _rich_text_to_md(rich_text: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for span in rich_text:
        text = span.get("plain_text", "")
        ann = span.get("annotations", {}) or {}
        # Order matters: code is innermost so it wraps the raw text first,
        # then bold/italic wrap around it.
        if ann.get("code"):
            text = f"`{text}`"
        if ann.get("bold"):
            text = f"**{text}**"
        if ann.get("italic"):
            text = f"*{text}*"
        # Notion exposes the URL on either ``text.link`` or the top-level
        # ``href`` -- prefer the structured one but fall back to href.
        link_obj = (span.get("text") or {}).get("link")
        url = (link_obj or {}).get("url") if isinstance(link_obj, dict) else None
        if not url:
            url = span.get("href")
        if url:
            text = f"[{text}]({url})"
        parts.append(text)
    return "".join(parts)


# ---------------------------------------------------------------------------
# Markdown -> Notion blocks
# ---------------------------------------------------------------------------


def markdown_to_blocks(md: str) -> list[dict[str, Any]]:
    """Parse a subset of markdown into Notion block dicts.

    Supported: H1/H2/H3, bulleted list, numbered list, todo, quote,
    fenced code, divider, paragraph. Anything unrecognised becomes a
    paragraph with the raw line(s) as plain text.
    """
    blocks: list[dict[str, Any]] = []
    lines = md.replace("\r\n", "\n").split("\n")
    i = 0
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        if not paragraph:
            return
        text = "\n".join(paragraph).strip()
        if text:
            blocks.append(_paragraph_block(text))
        paragraph = []

    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()

        # Fenced code block -- consume until the closing fence.
        if stripped.startswith("```"):
            flush_paragraph()
            lang = stripped[3:].strip()
            i += 1
            buf: list[str] = []
            while i < len(lines) and not lines[i].lstrip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1  # skip closing fence (or end-of-input)
            blocks.append(
                {
                    "object": "block",
                    "type": "code",
                    "code": {
                        "rich_text": _plain_spans("\n".join(buf)),
                        "language": _normalize_code_language(lang),
                    },
                }
            )
            continue

        # Divider
        if stripped in {"---", "***", "___"}:
            flush_paragraph()
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            i += 1
            continue

        # Headings
        heading_match = re.match(r"(#{1,3})\s+(.*)$", stripped)
        if heading_match:
            flush_paragraph()
            level = len(heading_match.group(1))
            blocks.append(_heading_block(level, heading_match.group(2).strip()))
            i += 1
            continue

        # Todo
        todo_match = re.match(r"[-*]\s*\[( |x|X)\]\s+(.*)$", stripped)
        if todo_match:
            flush_paragraph()
            checked = todo_match.group(1).lower() == "x"
            blocks.append(
                {
                    "object": "block",
                    "type": "to_do",
                    "to_do": {
                        "rich_text": _md_inline_to_rich_text(todo_match.group(2)),
                        "checked": checked,
                    },
                }
            )
            i += 1
            continue

        # Bulleted list
        if stripped.startswith(("- ", "* ")):
            flush_paragraph()
            blocks.append(
                {
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text": _md_inline_to_rich_text(stripped[2:].strip())},
                }
            )
            i += 1
            continue

        # Numbered list
        numbered_match = re.match(r"\d+\.\s+(.*)$", stripped)
        if numbered_match:
            flush_paragraph()
            blocks.append(
                {
                    "object": "block",
                    "type": "numbered_list_item",
                    "numbered_list_item": {"rich_text": _md_inline_to_rich_text(numbered_match.group(1))},
                }
            )
            i += 1
            continue

        # Quote (collect contiguous ``> `` lines into one block)
        if stripped.startswith("> "):
            flush_paragraph()
            quote_lines: list[str] = []
            while i < len(lines) and lines[i].lstrip().startswith("> "):
                quote_lines.append(lines[i].lstrip()[2:])
                i += 1
            blocks.append(
                {
                    "object": "block",
                    "type": "quote",
                    "quote": {"rich_text": _md_inline_to_rich_text("\n".join(quote_lines))},
                }
            )
            continue

        # Skipped-block placeholder we round-tripped from a previous sync
        if stripped.startswith("<!-- skipped unsupported block:"):
            i += 1
            continue

        # Blank line ends a paragraph
        if not stripped:
            flush_paragraph()
            i += 1
            continue

        paragraph.append(line)
        i += 1

    flush_paragraph()
    return blocks


def _heading_block(level: int, text: str) -> dict[str, Any]:
    key = f"heading_{level}"
    return {
        "object": "block",
        "type": key,
        key: {"rich_text": _md_inline_to_rich_text(text)},
    }


def _paragraph_block(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": _md_inline_to_rich_text(text)},
    }


# ---------------------------------------------------------------------------
# Inline rich-text parsing
# ---------------------------------------------------------------------------


_INLINE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Order matters only for ``search``: each pass picks the earliest match
    # across all patterns, so overlapping syntaxes are resolved left-to-right.
    # ``link`` first because ``[text](url)`` contains characters that bold /
    # italic patterns won't match anyway, and we want to capture the link
    # whole rather than parse its label as an inline run.
    ("link", re.compile(r"\[([^\]]+)\]\(([^)]+)\)")),
    ("code", re.compile(r"`([^`]+)`")),
    ("bold", re.compile(r"\*\*([^*]+)\*\*|__([^_]+)__")),
    ("italic", re.compile(r"\*([^*]+)\*|_([^_]+)_")),
]


_MAX_RICH_TEXT_LEN = 2000


def _md_inline_to_rich_text(text: str) -> list[dict[str, Any]]:
    """Tokenize inline markdown into Notion ``rich_text`` spans.

    Greedy / non-overlapping. Unmatched stretches become plain text spans,
    chunked at Notion's 2000-char-per-span ceiling.
    """
    if not text:
        return []
    out: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(text):
        best: tuple[int, str, re.Match[str]] | None = None
        for kind, pattern in _INLINE_PATTERNS:
            match = pattern.search(text, cursor)
            if match is None:
                continue
            if best is None or match.start() < best[0]:
                best = (match.start(), kind, match)
        if best is None:
            out.extend(_plain_spans(text[cursor:]))
            break
        start, kind, match = best
        if start > cursor:
            out.extend(_plain_spans(text[cursor:start]))
        out.append(_styled_span(kind, match))
        cursor = match.end()
    return out


def _styled_span(kind: str, match: re.Match[str]) -> dict[str, Any]:
    if kind == "link":
        return {
            "type": "text",
            "text": {"content": match.group(1), "link": {"url": match.group(2)}},
            "annotations": _default_annotations(),
        }
    if kind == "code":
        return {
            "type": "text",
            "text": {"content": match.group(1)},
            "annotations": _default_annotations(code=True),
        }
    if kind == "bold":
        return {
            "type": "text",
            "text": {"content": match.group(1) or match.group(2)},
            "annotations": _default_annotations(bold=True),
        }
    if kind == "italic":
        return {
            "type": "text",
            "text": {"content": match.group(1) or match.group(2)},
            "annotations": _default_annotations(italic=True),
        }
    raise ValueError(f"unknown inline kind: {kind}")


def _plain_spans(text: str) -> list[dict[str, Any]]:
    if not text:
        return []
    spans: list[dict[str, Any]] = []
    for i in range(0, len(text), _MAX_RICH_TEXT_LEN):
        chunk = text[i : i + _MAX_RICH_TEXT_LEN]
        spans.append(
            {
                "type": "text",
                "text": {"content": chunk},
                "annotations": _default_annotations(),
            }
        )
    return spans


def _default_annotations(**overrides: bool) -> dict[str, Any]:
    base: dict[str, Any] = {
        "bold": False,
        "italic": False,
        "strikethrough": False,
        "underline": False,
        "code": False,
        "color": "default",
    }
    base.update(overrides)
    return base


# Notion accepts a fixed list of code-block languages. We map common
# aliases (``py`` -> ``python``) and fall back to ``plain text`` for
# anything unrecognised rather than reject the write.
_NOTION_CODE_LANGUAGES = frozenset(
    {
        "abap",
        "arduino",
        "bash",
        "basic",
        "c",
        "clojure",
        "coffeescript",
        "c++",
        "c#",
        "css",
        "dart",
        "diff",
        "docker",
        "elixir",
        "elm",
        "erlang",
        "flow",
        "fortran",
        "f#",
        "gherkin",
        "glsl",
        "go",
        "graphql",
        "groovy",
        "haskell",
        "html",
        "java",
        "javascript",
        "json",
        "julia",
        "kotlin",
        "latex",
        "less",
        "lisp",
        "livescript",
        "lua",
        "makefile",
        "markdown",
        "markup",
        "matlab",
        "mermaid",
        "nix",
        "objective-c",
        "ocaml",
        "pascal",
        "perl",
        "php",
        "plain text",
        "powershell",
        "prolog",
        "protobuf",
        "python",
        "r",
        "reason",
        "ruby",
        "rust",
        "sass",
        "scala",
        "scheme",
        "scss",
        "shell",
        "sql",
        "swift",
        "typescript",
        "vb.net",
        "verilog",
        "vhdl",
        "visual basic",
        "webassembly",
        "xml",
        "yaml",
    }
)

_CODE_LANG_ALIASES = {
    "py": "python",
    "js": "javascript",
    "ts": "typescript",
    "rb": "ruby",
    "sh": "shell",
    "zsh": "shell",
    "yml": "yaml",
    "tsx": "typescript",
    "jsx": "javascript",
}


def _normalize_code_language(lang: str) -> str:
    lang = (lang or "").strip().lower()
    if not lang:
        return "plain text"
    lang = _CODE_LANG_ALIASES.get(lang, lang)
    if lang in _NOTION_CODE_LANGUAGES:
        return lang
    return "plain text"
