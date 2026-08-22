"""Shared helpers used by Context implementations."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any

from agno.context.types import Answer


def answer_from_run(output: Any) -> Answer:
    """Turn an Agno RunOutput into an Answer."""
    text = output.get_content_as_string() if hasattr(output, "get_content_as_string") else str(output.content)
    return Answer(text=text or None)


def serialize_answer(answer: Answer) -> dict:
    """Build the JSON payload returned to the calling agent.

    Omit empty fields so the calling agent doesn't see filler. Today
    no provider populates ``Answer.results`` (the ``Document`` slot
    is reserved for providers that want to return structured hits
    alongside synthesized text); shipping ``"results": []`` on every
    call is dead weight in the prompt. ``text`` is omitted when None.
    If both are absent the payload is ``{}`` — honest "this tool
    returned nothing" signal to the calling agent.
    """
    payload: dict = {}
    if answer.results:
        payload["results"] = [asdict(r) for r in answer.results]
    if answer.text is not None:
        payload["text"] = answer.text
    return payload


def sanitize_id(raw: str) -> str:
    """Normalize a raw string into a valid tool-name suffix."""
    s = re.sub(r"[^a-z0-9]+", "_", raw.lower())
    return s.strip("_") or "context"


def _answer_chunk(answer: Answer) -> str:
    """Wrap an Answer as a JSON string for yielding from tools."""
    return json.dumps(serialize_answer(answer))


def _error_chunk(msg: str) -> str:
    """Wrap an error message as a JSON string for yielding from tools."""
    return json.dumps({"error": msg})
