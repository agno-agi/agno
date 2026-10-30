"""Helpers for building Lark interactive card payloads.

Lark supports two relevant message types for a chat bot:

* ``text``  — plain text only, no markdown rendering. Edited via ``PUT /im/v1/messages/:message_id``.
* ``interactive`` — a JSON *card* that renders markdown, dividers, notes, etc.
  Updated in place via ``PATCH /im/v1/messages/:message_id``.

Streaming responses rely on the interactive card: the bot sends a card first,
then patches its content as tokens arrive. Cards therefore need
``update_multi: true`` so the update is visible to everyone in a shared chat.

References:
  - Card structure: https://open.larksuite.com/document/uAjLw4CM/ukTMukTMukTM/feishu-cards/card-components/content-components/rich-text
  - PATCH message:  https://open.larksuite.com/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message/patch
"""

from __future__ import annotations

import json
from typing import List, Optional

# Lark caps interactive card content at 30 KB. We leave headroom for the card
# envelope + status note so the PATCH never exceeds the server limit.
LARK_MAX_CARD_CONTENT_BYTES = 28_000


def build_card_content(markdown_text: str = "", status_lines: Optional[List[str]] = None) -> str:
    """Build a Lark interactive card JSON string.

    The card renders ``status_lines`` (tool/reasoning progress) as a grey *note*
    block above the main ``markdown_text`` — mirroring the blockquote pattern
    used by the Telegram interface's streaming display.

    Args:
        markdown_text: The agent response text (markdown is rendered by Lark).
        status_lines: Optional list of short status lines (e.g. "search...").

    Returns:
        A JSON-encoded card string ready for the ``content`` field of
        ``msg_type: "interactive"`` messages or PATCH requests.
    """
    elements: List[dict] = []

    if status_lines:
        # ``note`` renders as small grey text — ideal for transient status.
        elements.append(
            {
                "tag": "note",
                "elements": [{"tag": "plain_text", "content": "\n".join(status_lines)}],
            }
        )

    if markdown_text:
        elements.append({"tag": "markdown", "content": markdown_text})

    # An empty card is invalid; always include at least one element.
    if not elements:
        elements.append({"tag": "markdown", "content": ""})

    card = {
        # wide_screen_mode keeps cards readable on desktop; update_multi allows
        # in-place PATCH updates visible to all chat members.
        "config": {"wide_screen_mode": True, "update_multi": True},
        "elements": elements,
    }
    return json.dumps(card, ensure_ascii=False)


def truncate_markdown(text: str, max_bytes: int = LARK_MAX_CARD_CONTENT_BYTES) -> str:
    """Truncate ``text`` so its UTF-8 encoding fits within ``max_bytes``.

    Lark rejects cards whose content exceeds 30 KB. Streaming accumulates text
    progressively, so we trim from the end (preserving the head of the response)
    when it grows too long.
    """
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    # Cut on a UTF-8 boundary to avoid producing invalid characters.
    truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return truncated + "\n\n…(truncated)"
