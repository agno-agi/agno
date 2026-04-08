import re

# Preserves Discord mentions (<@id>, <#id>, <:emoji:id>, <a:emoji:id>, <@&role>)
_HTML_TAG_RE = re.compile(r"<(?![#@:a][:\w]|a:)(?!/)[^>]+>|</[^>]+>")
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", flags=re.MULTILINE)
_FENCE_OPEN_RE = re.compile(r"^(?P<fence>`{3,})(?:\w+)?$")
_COMPLETED_FENCE_RE = re.compile(r"`{3,}[^`]*`{3,}", re.DOTALL)


def strip_html_tags(text: str) -> str:
    return _HTML_TAG_RE.sub("", text)


def normalize_headings(text: str) -> str:
    # Bot messages ignore # headings; bold is the closest equivalent
    return _HEADING_RE.sub(r"**\1**", text)


def close_unterminated_fences(text: str) -> str:
    # Streaming chunks may split mid-code-block
    open_fence = None
    for line in text.splitlines():
        stripped = line.strip()
        if open_fence is None:
            match = _FENCE_OPEN_RE.match(stripped)
            if match:
                open_fence = match.group("fence")
        elif stripped == open_fence:
            open_fence = None

    if open_fence is not None:
        if not text.endswith("\n"):
            text += "\n"
        text += open_fence

    cleaned = _COMPLETED_FENCE_RE.sub("", text)
    if cleaned.count("`") % 2 != 0:
        text += "`"

    return text


def normalize_for_streaming(text: str) -> str:
    return strip_html_tags(normalize_headings(text))


def normalize_discord_markdown(text: str) -> str:
    text = strip_html_tags(text)
    text = normalize_headings(text)
    text = close_unterminated_fences(text)
    return text
