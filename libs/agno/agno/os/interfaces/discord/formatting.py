import re

# Strips HTML but preserves all Discord angle-bracket markup:
# <@id>, <@!id>, <#id>, <@&role>, <:emoji:id>, <a:emoji:id>, <t:timestamp:style>
_HTML_TAG_RE = re.compile(r"<(?![#@:a][:\w&!]|a:|t:)(?!/)[^>]+>|</[^>]+>")

_FENCE_OPEN_RE = re.compile(r"^(?P<fence>`{3,})(?:\w+)?$")

# Matches self-contained ```...``` blocks; used to exclude them from backtick parity check
_CLOSED_FENCE_BLOCK_RE = re.compile(r"`{3,}[^`]*`{3,}", re.DOTALL)


def strip_html_tags(text: str) -> str:
    return _HTML_TAG_RE.sub("", text)


def close_unterminated_fences(text: str) -> str:
    # Phase 1: Track triple-backtick fence state and close any open fence
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

    # Phase 2: Fix orphaned inline backticks (odd count outside fenced blocks)
    without_closed_fences = _CLOSED_FENCE_BLOCK_RE.sub("", text)
    if without_closed_fences.count("`") % 2 != 0:
        text += "`"

    return text


def normalize_for_streaming(text: str) -> str:
    # Lightweight — omits fence closing since chunks may be mid-block.
    # Discord renders # headings, **bold**, *italic*, `code`, and the
    # full markdown subset natively; only HTML tags need stripping.
    return strip_html_tags(text)


def normalize_discord_markdown(text: str) -> str:
    # Full normalization for complete messages — closes unterminated fences
    text = strip_html_tags(text)
    text = close_unterminated_fences(text)
    return text
