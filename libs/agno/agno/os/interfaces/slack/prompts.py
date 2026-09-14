"""Suggested prompts shown at the top of the app's Messages tab."""

from __future__ import annotations

from typing import Any, Dict, List, Union

# Slack shows at most four prompts and truncates long ones
MAX_PROMPTS = 4
MAX_PROMPT_CHARS = 300

DEFAULT_PROMPTS: List[Dict[str, str]] = [
    {"title": "Help", "message": "What can you help me with?"},
    {"title": "Search", "message": "Search the web for..."},
]

# A prompt is the text to send; a dict adds a separate short title
Prompt = Union[str, Dict[str, str]]
PromptList = List[Dict[str, str]]


def normalize_prompts(raw: Any) -> PromptList:
    """Keep only well-formed ``{title, message}`` entries, capped at Slack's limit."""
    prompts: PromptList = []
    for item in raw or []:
        if isinstance(item, str):
            title = message = item
        elif isinstance(item, dict):
            message = str(item.get("message") or "").strip()
            title = str(item.get("title") or message).strip()
        else:
            continue
        if not message:
            continue
        prompts.append({"title": title[:MAX_PROMPT_CHARS], "message": message[:MAX_PROMPT_CHARS]})
        if len(prompts) >= MAX_PROMPTS:
            break
    return prompts
