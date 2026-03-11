# Markdown to Telegram HTML converter.
#
# Adapted from formatter-chatgpt-telegram (MIT License)
# https://github.com/Latand/formatter-chatgpt-telegram
#
# Telegram supports: <b>, <i>, <s>, <u>, <code>, <pre>, <a>,
# <blockquote>, <tg-spoiler>, <tg-emoji>.

import html
import re

_HTML_ENTITY_RE = re.compile(r"&(?:lt|gt|amp|quot|apos|#\d+|#x[\da-fA-F]+);")


def _is_pre_escaped(text: str) -> bool:
    return bool(_HTML_ENTITY_RE.search(text))


def _unescape_html(text: str) -> str:
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&apos;", "'")
    return text


def escape_code_content(text: str) -> str:
    # LLMs sometimes pre-escape HTML entities in code blocks.
    # Unescape first, then re-escape exactly once to avoid double-escaping.
    if _is_pre_escaped(text):
        text = _unescape_html(text)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def escape_html(text: str) -> str:
    return html.escape(text, quote=False)


_CODE_BLOCK_RE = re.compile(
    r"(?P<fence>`{3,})(?P<lang>\w+)?\n?[\s\S]*?(?<=\n)?(?P=fence)",
    flags=re.DOTALL,
)

_CODE_BLOCK_EXTRACT_RE = re.compile(
    r"(?P<fence>`{3,})(?P<lang>\w+)?\n?(?P<code>[\s\S]*?)(?<=\n)?(?P=fence)",
    flags=re.DOTALL,
)


def _count_unescaped_backticks(text: str) -> int:
    count = 0
    for index, char in enumerate(text):
        if char != "`":
            continue
        backslashes = 0
        j = index - 1
        while j >= 0 and text[j] == "\\":
            backslashes += 1
            j -= 1
        if backslashes % 2 == 0:
            count += 1
    return count


def _ensure_closing_delimiters(text: str) -> str:
    open_fence = None
    for line in text.splitlines():
        stripped = line.strip()
        if open_fence is None:
            match = re.match(r"^(?P<fence>`{3,})(?P<lang>\w+)?$", stripped)
            if match:
                open_fence = match.group("fence")
        else:
            if stripped.endswith(open_fence):
                open_fence = None

    if open_fence is not None:
        if not text.endswith("\n"):
            text += "\n"
        text += open_fence

    cleaned = _CODE_BLOCK_RE.sub("", text)
    if cleaned.count("```") % 2 != 0:
        text += "```"

    cleaned = _CODE_BLOCK_RE.sub("", text)
    if _count_unescaped_backticks(cleaned) % 2 != 0:
        text += "`"

    return text


def _extract_code_blocks(text: str) -> tuple[str, dict[str, str]]:
    text = _ensure_closing_delimiters(text)
    placeholders: list[str] = []
    blocks: dict[str, str] = {}
    modified = text

    for match in _CODE_BLOCK_EXTRACT_RE.finditer(text):
        language = match.group("lang") or ""
        code = match.group("code")
        escaped = escape_code_content(code)
        placeholder = f"\x00CODEBLOCK{len(placeholders)}\x00"
        placeholders.append(placeholder)
        if language:
            blocks[placeholder] = f'<pre><code class="language-{language}">{escaped}</code></pre>'
        else:
            blocks[placeholder] = f"<pre><code>{escaped}</code></pre>"
        modified = modified.replace(match.group(0), placeholder, 1)

    return modified, blocks


def _reinsert_code_blocks(text: str, blocks: dict[str, str]) -> str:
    for placeholder, html_block in blocks.items():
        text = text.replace(placeholder, html_block, 1)
    return text


_INLINE_CODE_RE = re.compile(r"`([^`]+)`")


def _extract_inline_code(text: str) -> tuple[str, dict[str, str]]:
    placeholders: list[str] = []
    snippets: dict[str, str] = {}

    def _replace(m: re.Match) -> str:
        snippet = m.group(1)
        placeholder = f"\x00INLINECODE{len(placeholders)}\x00"
        placeholders.append(placeholder)
        snippets[placeholder] = snippet
        return placeholder

    return _INLINE_CODE_RE.sub(_replace, text), snippets


def _combine_blockquotes(text: str) -> str:
    lines = text.split("\n")
    combined: list[str] = []
    quote_lines: list[str] = []
    in_quote = False
    expandable = False

    for line in lines:
        if line.startswith("**>"):
            in_quote = True
            expandable = True
            quote_lines.append(line[3:].strip())
        elif line.startswith(">**") and (len(line) == 3 or line[3].isspace()):
            in_quote = True
            expandable = True
            quote_lines.append(line[3:].strip())
        elif line.startswith(">"):
            if not in_quote:
                in_quote = True
                expandable = False
            quote_lines.append(line[1:].strip())
        else:
            if in_quote:
                tag = "blockquote expandable" if expandable else "blockquote"
                combined.append(f"<{tag}>" + "\n".join(quote_lines) + "</blockquote>")
                quote_lines = []
                in_quote = False
                expandable = False
            combined.append(line)

    if in_quote:
        tag = "blockquote expandable" if expandable else "blockquote"
        combined.append(f"<{tag}>" + "\n".join(quote_lines) + "</blockquote>")

    return "\n".join(combined)


_BOLD_RE = re.compile(
    r"(?<!\\)\*\*(?!\*)(?=\S)(.*?)(?<=\S)(?<!\*)\*\*(?!\*)",
    re.DOTALL,
)
_UNDERLINE_RE = re.compile(
    r"(?<!\\)(?<![A-Za-z0-9_])__(?=\S)(.*?)(?<=\S)__(?![A-Za-z0-9_])",
    re.DOTALL,
)
_ITALIC_UNDERSCORE_RE = re.compile(
    r"(?<!\\)(?<![A-Za-z0-9_])_(?=\S)(.*?)(?<=\S)_(?![A-Za-z0-9_])",
    re.DOTALL,
)
_STRIKETHROUGH_RE = re.compile(r"(?<!\\)~~(?=\S)(.*?)(?<=\S)~~", re.DOTALL)
_SPOILER_RE = re.compile(r"(?<!\\)\|\|(?=\S)([^\n]*?)(?<=\S)\|\|")
_ITALIC_STAR_RE = re.compile(
    r"(?<![A-Za-z0-9\\*])\*(?!\*)(?=\S)(.*?)(?<![\s\\*])\*(?![A-Za-z0-9\\*])",
    re.DOTALL,
)

_PATTERN_MAP: dict[str, re.Pattern[str]] = {
    "**": _BOLD_RE,
    "__": _UNDERLINE_RE,
    "_": _ITALIC_UNDERSCORE_RE,
    "~~": _STRIKETHROUGH_RE,
    "||": _SPOILER_RE,
}


def _split_by_tag(text: str, md_tag: str, html_tag: str) -> str:
    pattern = _PATTERN_MAP.get(md_tag)
    if pattern is None:
        escaped = re.escape(md_tag)
        pattern = re.compile(rf"(?<!\\){escaped}(?=\S)(.*?)(?<=\S){escaped}", re.DOTALL)

    def _wrap(m: re.Match) -> str:
        inner = m.group(1)
        if not inner.strip():
            return m.group(0)
        if md_tag == "**" and not re.search(r"[^\s*]", inner):
            return m.group(0)
        if html_tag == 'span class="tg-spoiler"':
            return f'<span class="tg-spoiler">{inner}</span>'
        return f"<{html_tag}>{inner}</{html_tag}>"

    return pattern.sub(_wrap, text)


def _unescape_tags(text: str) -> str:
    # Blockquote tags get escaped during HTML char conversion; restore them
    text = text.replace("&lt;blockquote&gt;", "<blockquote>")
    text = text.replace("&lt;blockquote expandable&gt;", "<blockquote expandable>")
    text = text.replace("&lt;/blockquote&gt;", "</blockquote>")
    # Spoiler spans
    text = text.replace('&lt;span class="tg-spoiler"&gt;', '<span class="tg-spoiler">')
    text = text.replace("&lt;/span&gt;", "</span>")
    return text


_TG_EMOJI_RE = re.compile(r"!\[([^\]]*)\]\(tg://emoji\?id=(\d+)\)")
_LINK_RE = re.compile(r"(?:!?)\[((?:[^\[\]]|\[.*?\])*)\]\(([^)]+)\)")


def markdown_to_telegram_html(text: str) -> str:
    # 1. Extract code blocks (protect from formatting)
    output, block_map = _extract_code_blocks(text)

    # 2. Combine blockquote lines into <blockquote> tags
    output = _combine_blockquotes(output)

    # 3. Extract inline code (protect from formatting)
    output, inline_snippets = _extract_inline_code(output)

    # 4. Escape HTML entities in remaining text
    output = escape_html(output)

    # 5. Headings → bold
    output = re.sub(r"^(#{1,6})\s+(.+)$", r"<b>\2</b>", output, flags=re.MULTILINE)

    # 6. List markers → bullet
    output = re.sub(r"^(\s*)[\-\*]\s+(.+)$", "\\1\u2022 \\2", output, flags=re.MULTILINE)

    # 7. Triple markers (bold+italic, underline+italic)
    output = re.sub(
        r"(?<!\*)\*\*\*(?!\*)(?=\S)(.*?)(?<=\S)(?<!\*)\*\*\*(?!\*)",
        r"<b><i>\1</i></b>",
        output,
        flags=re.DOTALL,
    )
    output = re.sub(
        r"(?<!_)___(?!_)(?=\S)(.*?)(?<=\S)(?<!_)___(?!_)",
        r"<u><i>\1</i></u>",
        output,
        flags=re.DOTALL,
    )

    # 8. Paired markers → HTML tags
    output = _split_by_tag(output, "**", "b")
    output = _split_by_tag(output, "__", "u")
    output = _split_by_tag(output, "~~", "s")
    output = _split_by_tag(output, "||", 'span class="tg-spoiler"')

    # 9. Star italic (after bold, so ** is consumed first)
    output = _ITALIC_STAR_RE.sub(r"<i>\1</i>", output)

    # 10. Underscore italic (after underline, so __ is consumed first)
    output = _split_by_tag(output, "_", "i")

    # 11. Remove ChatGPT citation markers
    output = re.sub(r"\u3010[^\u3011]+\u3011", "", output)

    # 12. Telegram custom emoji: ![emoji](tg://emoji?id=123)
    output = _TG_EMOJI_RE.sub(r'<tg-emoji emoji-id="\2">\1</tg-emoji>', output)

    # 13. Links and images (images rendered as links)
    # Step 4 escapes &<> but not quotes — need to escape " in href attributes
    def _link_replacer(m: re.Match) -> str:
        text, href = m.group(1), m.group(2).replace('"', "&quot;")
        return f'<a href="{href}">{text}</a>'

    output = _LINK_RE.sub(_link_replacer, output)

    # 14. Reinsert inline code
    for placeholder, snippet in inline_snippets.items():
        escaped = escape_code_content(snippet)
        output = output.replace(placeholder, f"<code>{escaped}</code>")

    # 15. Reinsert code blocks
    output = _reinsert_code_blocks(output, block_map)

    # 16. Unescape blockquote/spoiler tags that got HTML-escaped
    output = _unescape_tags(output)

    # 17. Collapse excessive newlines
    output = re.sub(r"\n{3,}", "\n\n", output)

    return output.strip()
