"""Streaming Ollama calls must pass response_format like non-stream invoke."""

from __future__ import annotations

from typing import Iterator
from unittest.mock import MagicMock

from pydantic import BaseModel

from agno.models.message import Message
from agno.models.ollama.chat import Ollama


class _Out(BaseModel):
    answer: str


def test_invoke_stream_forwards_response_format_via_prepare_kwargs(monkeypatch) -> None:
    model = Ollama(id="llama3.2")
    captured: dict[str, object] = {}

    def fake_prepare(*, response_format=None, tools=None):
        captured["response_format"] = response_format
        captured["tools"] = tools
        return {"format": "json"}

    class _Client:
        def chat(self, **kwargs):
            captured["chat_kwargs"] = kwargs

            def _gen() -> Iterator[dict]:
                yield {"message": {"role": "assistant", "content": "{}"}}

            return _gen()

    monkeypatch.setattr(model, "_prepare_request_kwargs_for_invoke", fake_prepare)
    monkeypatch.setattr(model, "get_client", lambda: _Client())

    assistant = Message(role="assistant", content="")
    list(
        model.invoke_stream(
            messages=[Message(role="user", content="hi")],
            assistant_message=assistant,
            response_format=_Out,
        )
    )

    assert captured["response_format"] is _Out
    assert captured["chat_kwargs"]["stream"] is True
    assert captured["chat_kwargs"]["format"] == "json"
