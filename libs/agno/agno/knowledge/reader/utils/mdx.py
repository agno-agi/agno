"""Convert MDX components to Markdown for indexing and page reads.

Preserve code fences, prose placeholders and relative indentation.
Unwrap unknown components while retaining their content.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Literal, Mapping, Optional

from agno.utils.markdown import FenceState, advance_code_fence

HTML_BLOCK = r"div|h[1-6]|video"
HTML_VOID = r"img|br|source|video"
BLOCK_OPEN = re.compile(rf"^\s*<(?P<name>[A-Z][A-Za-z]*|{HTML_BLOCK})(?P<attrs>\s[^<>]*?)?(?<!/)>\s*$")
BLOCK_CLOSE = re.compile(rf"^\s*</(?P<name>[A-Z][A-Za-z]*|{HTML_BLOCK})>\s*$")
SELF_CLOSING = re.compile(rf"^\s*<(?P<name>[A-Z][A-Za-z]*|{HTML_VOID})(?P<attrs>\s[^<>]*?)?\s*/>\s*$")
ONE_LINER = re.compile(r"^\s*<(?P<name>[A-Z][A-Za-z]*|h[1-6])(?P<attrs>\s[^<>]*?)?>(?P<body>.*)</(?P=name)>\s*$")
ATTR = re.compile(r"""([A-Za-z][\w-]*)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|\{([^}]*)\}|([^\s"'<>]+)))?""")
CALLOUTS = {"Note": "Note", "Warning": "Warning", "Tip": "Tip", "Info": "Info", "Check": "Check", "Callout": ""}
LABELLED = {"CodeBlockTab": "value", "Tab": "title", "Accordion": "title"}  # tag -> attribute that names it
_PLAIN_BLOCK_START = re.compile(r"^(?:[-*+]\s|\d+[.)]\s|#{1,6}\s|>|\||```|~~~)")


ComponentRenderer = Callable[[Mapping[str, str], str], str]


@dataclass
class _Context:
    step: int = 0
    aliases: Mapping[str, str] = field(default_factory=dict)
    renderers: Mapping[str, ComponentRenderer] = field(default_factory=dict)


def _attrs(raw: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for match in ATTR.finditer(raw or ""):
        key = match.group(1)
        value = next((g for g in match.groups()[1:] if g is not None), "")
        out[key] = value.strip()
    return out


def _dedent(lines: list[str]) -> list[str]:
    """Remove the indentation the JSX nesting added: the smallest indent of the block's non-blank lines."""
    indents = [len(line) - len(line.lstrip(" ")) for line in lines if line.strip()]
    if not indents:
        return ["" for _ in lines]
    depth = min(indents)
    return [line[depth:] if line.strip() else "" for line in lines]


def _find_close(lines: list[str], start: int, name: str) -> int | None:
    """Index of the closing tag matching an opening tag of `name` at start-1, fence-aware; None if unmatched."""
    depth = 1
    fence: FenceState | None = None
    for index in range(start, len(lines)):
        line = lines[index]
        was_code = fence is not None
        fence, delimiter = advance_code_fence(line, fence)
        if was_code or delimiter:
            continue
        opened = BLOCK_OPEN.match(line)
        if opened and opened.group("name") == name:
            depth += 1
            continue
        closed = BLOCK_CLOSE.match(line)
        if closed and closed.group("name") == name:
            depth -= 1
            if depth == 0:
                return index
    return None


def _joined_text(lines: list[str]) -> str | None:
    """The block's content as one line when it is plain prose, else None."""
    text = [line.strip() for line in lines if line.strip()]
    if not text or any(_PLAIN_BLOCK_START.match(line) or line.startswith("<") for line in text):
        return None
    return " ".join(text)


def _bullet(head: str, inner: list[str], ctx: _Context) -> list[str]:
    body = _walk(inner, ctx)
    if not head:
        return body
    text = _joined_text(body)
    if text is not None:
        return [f"- {head}: {text}"]
    if not any(line.strip() for line in body):
        return [f"- {head}"]
    return [f"- {head}"] + [f"  {line}" if line.strip() else "" for line in body]


def _render(name: str, attrs: dict[str, str], inner: list[str], ctx: _Context) -> list[str]:
    original_name = name
    name = ctx.aliases.get(name, name)
    renderer = ctx.renderers.get(original_name) or ctx.renderers.get(name)
    if renderer is not None:
        return renderer(MappingProxyType(attrs), "\n".join(_walk(inner, ctx))).split("\n")
    if name == "Steps":
        saved = ctx.step
        ctx.step = 0
        try:
            return [""] + _walk(inner, ctx) + [""]
        finally:
            ctx.step = saved
    if name == "Step":
        ctx.step = ctx.step + 1
        title = attrs.get("title", "")
        label = f"**Step {ctx.step}: {title}**" if title else f"**Step {ctx.step}**"
        return ["", label, ""] + _walk(inner, ctx) + [""]
    if name == "CodeBlockTabsTrigger":
        return []  # the tab's label; <CodeBlockTab value=...> carries it again
    if name in LABELLED:
        label = attrs.get(LABELLED[name], "")
        return ([""] + [f"**{label}**", ""] if label else [""]) + _walk(inner, ctx) + [""]
    if name in CALLOUTS:
        label = CALLOUTS[name] or (attrs.get("type", "note").capitalize() or "Note")
        body = _walk(inner, ctx)
        text = _joined_text(body)
        if text is not None:
            return ["", f"**{label}:** {text}", ""]
        return ["", f"**{label}:**"] + body + [""]
    if name == "Card":
        title, href = attrs.get("title", ""), attrs.get("href", "")
        head = f"[{title}]({href})" if title and href else f"**{title}**" if title else f"<{href}>" if href else ""
        return _bullet(head, inner, ctx)
    if name in ("ResponseField", "ParamField"):
        head = f"`{attrs['name']}`" if attrs.get("name") else ""
        details = [attrs["type"]] if attrs.get("type") else []
        if "required" in attrs:
            details.append("required")
        if attrs.get("default"):
            details.append(f"default {attrs['default']}")
        if head and details:
            head += f" ({', '.join(details)})"
        return _bullet(head, inner, ctx)
    if name == "Frame":
        caption = attrs.get("caption", "")
        return [""] + _walk(inner, ctx) + ([f"*{caption}*", ""] if caption else [""])
    if name in ("ImageZoom", "Image", "img"):
        src = attrs.get("src", "")
        return [f"![{attrs.get('alt', '')}]({src})"] if src else []
    if name in ("video", "Video", "source"):
        src = attrs.get("src", "")
        return [f"[Video]({src})"] if src else _walk(inner, ctx)
    if name == "br":
        return [""]
    if name == "Tooltip":
        tip = attrs.get("tip", "")
        text = _joined_text(_walk(inner, ctx)) or ""
        return [f"*{tip}*" if tip else text]
    if re.fullmatch(r"h[1-6]", name):
        text = " ".join(line.strip() for line in inner if line.strip())
        return ["", f"{'#' * int(name[1])} {text}", ""] if text else []
    return [""] + _walk(inner, ctx) + [""]  # unknown component: unwrap


def _walk(lines: list[str], ctx: _Context) -> list[str]:
    out: list[str] = []
    index = 0
    fence: FenceState | None = None
    while index < len(lines):
        line = lines[index]
        was_code = fence is not None
        fence, delimiter = advance_code_fence(line, fence)
        if was_code or delimiter:
            out.append(line)
            index += 1
            continue
        opened = BLOCK_OPEN.match(line)
        if opened:
            name = opened.group("name")
            end = _find_close(lines, index + 1, name)
            if end is None:
                out.extend(_render(name, _attrs(opened.group("attrs")), [], ctx))
                index += 1
                continue
            out.extend(_render(name, _attrs(opened.group("attrs")), _dedent(lines[index + 1 : end]), ctx))
            index = end + 1
            continue
        one = ONE_LINER.match(line)
        if one:
            out.extend(_render(one.group("name"), _attrs(one.group("attrs")), [one.group("body").strip()], ctx))
            index += 1
            continue
        closed = SELF_CLOSING.match(line)
        if closed:
            out.extend(_render(closed.group("name"), _attrs(closed.group("attrs")), [], ctx))
            index += 1
            continue
        if BLOCK_CLOSE.match(line):
            index += 1  # a stray closing tag
            continue
        out.append(line)
        index += 1
    return out


def _collapse_blank_lines(lines: list[str]) -> list[str]:
    """At most one blank line between blocks outside fences; fences keep their blank lines."""
    out: list[str] = []
    fence: FenceState | None = None
    for line in lines:
        was_code = fence is not None
        fence, delimiter = advance_code_fence(line, fence)
        if not (was_code or delimiter) and not line.strip() and out and not out[-1].strip():
            continue
        out.append(line)
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return out


def normalize_mdx(
    markdown: str,
    *,
    component_aliases: Optional[Mapping[str, str]] = None,
    component_renderers: Optional[Mapping[str, ComponentRenderer]] = None,
) -> str:
    """Convert whole-line documentation components, preserving fenced code.

    Supports steps, tabs, callouts, cards, fields, media and transparent wrappers.
    Unknown components are unwrapped. Inline JSX and multiline attributes are not
    evaluated. Attribute expressions are literal strings, never Python/JavaScript.
    Aliases select a built-in component; renderers receive parsed attributes and
    normalized inner Markdown. Call this once on source text before chunking.
    """
    if "<" not in markdown:
        return markdown
    ctx = _Context(aliases=dict(component_aliases or {}), renderers=dict(component_renderers or {}))
    lines = _collapse_blank_lines(_walk(markdown.split("\n"), ctx))
    return "\n".join(lines) + ("\n" if markdown.endswith("\n") and lines else "")


PREAMBLE_HEADER = "> ## Documentation Index"


def _strip_preamble(markdown: str) -> str:
    """Drop the site's '> ## Documentation Index' blockquote that precedes every page."""
    if not markdown.startswith(PREAMBLE_HEADER):
        return markdown
    lines = markdown.splitlines()
    i = 0
    while i < len(lines) and lines[i].startswith(">"):
        i += 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    return "\n".join(lines[i:]) + ("\n" if markdown.endswith("\n") else "")


# The serializer escapes markdown punctuation in text nodes (`QWEN\_API\_KEY`, `List\[Message]`).
# Not `|` (table cells) and not backticks: a code span may hold a literal backslash.
MD_ESCAPE = re.compile(r"\\([_\[\]*~<>&])")


def _unescape_prose(markdown: str) -> str:
    """Decode the HTML entities and drop the markdown backslash escapes the site's serializer
    emits in prose (never inside code fences), so identifiers read and search as written."""
    out = []
    fence: FenceState | None = None
    for line in markdown.splitlines():
        was_code = fence is not None
        fence, delimiter = advance_code_fence(line, fence)
        if not (was_code or delimiter):
            if "&" in line:
                line = html.unescape(line)
            if "\\" in line:
                line = MD_ESCAPE.sub(r"\1", line)
        out.append(line)
    return "\n".join(out) + ("\n" if markdown.endswith("\n") else "")


@dataclass(frozen=True)
class DocumentationMarkdown:
    """Optional pure source transform for Knowledge.sync_pages/async_sync_pages.

    ``markdown`` returns input verbatim. ``fumadocs`` normalizes components,
    removes the leading Documentation Index blockquote and decodes serializer
    escapes outside fences, including inline code. ``mintlify`` normalizes the
    same component vocabulary and preamble but keeps escapes/entities by default.
    Fumadocs decoding deliberately preserves its existing html.unescape semantics;
    use unescape_serializer=False for authored Markdown or literal HTML examples.
    Profiles normalize CRLF, trim surrounding whitespace and add a final LF.
    They reject empty pages. No reader changes behavior unless explicitly called.

    This is a source transform, not an MDX runtime or an HTML sanitizer. Repeated
    decoding of escaped tags/entities is not guaranteed idempotent. Keep the
    original source and version the transform when changing an existing index.
    """

    profile: Literal["markdown", "fumadocs", "mintlify"] = "markdown"
    strip_index_preamble: bool = True
    unescape_serializer: Optional[bool] = None
    component_aliases: Mapping[str, str] = field(default_factory=dict)
    component_renderers: Mapping[str, ComponentRenderer] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.profile not in ("markdown", "fumadocs", "mintlify"):
            raise ValueError("Unknown documentation Markdown profile")
        object.__setattr__(self, "component_aliases", MappingProxyType(dict(self.component_aliases)))
        object.__setattr__(self, "component_renderers", MappingProxyType(dict(self.component_renderers)))

    def __call__(self, text: str, *, path: str) -> str:
        if self.profile == "markdown":
            return text
        if self.strip_index_preamble:
            text = _strip_preamble(text)
        text = normalize_mdx(
            text, component_aliases=self.component_aliases, component_renderers=self.component_renderers
        )
        if self.unescape_serializer is True or (self.unescape_serializer is None and self.profile == "fumadocs"):
            text = _unescape_prose(text)
        content = text.replace("\r\n", "\n").strip()
        if not content:
            raise ValueError("empty page")
        return content + "\n"
