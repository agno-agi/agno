"""An Agent run whose input is a Message carrying image bytes completes and is stored."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from openai.types.chat import ChatCompletion

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media import Image
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.run.base import RunStatus

PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"


def _completion() -> ChatCompletion:
    return ChatCompletion.model_validate(
        {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 0,
            "model": "gpt-test",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "A tiny image."},
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    )


def _agent(tmp_path) -> Agent:
    model = OpenAIChat(id="gpt-test", api_key="test")
    client = MagicMock()
    client.is_closed.return_value = False
    client.chat.completions.create.return_value = _completion()
    async_client = MagicMock()
    async_client.is_closed.return_value = False
    async_client.chat.completions.create = AsyncMock(return_value=_completion())
    model.client = client
    model.async_client = async_client
    return Agent(model=model, db=SqliteDb(db_file=str(tmp_path / "agent.db")))


def _message() -> Message:
    return Message(role="user", content="Describe this", images=[Image(content=PNG_BYTES, format="png")])


def _assert_stored(agent: Agent, run_id: str) -> None:
    session = agent.get_session()
    assert session is not None and session.runs
    stored = next(run for run in session.runs if run.run_id == run_id)
    assert stored.input is not None
    assert stored.input.input_content_string()


def test_run_with_image_bytes_message_input(tmp_path):
    agent = _agent(tmp_path)

    response = agent.run(input=_message())

    assert response.status == RunStatus.completed
    assert response.content == "A tiny image."
    _assert_stored(agent, response.run_id)


@pytest.mark.asyncio
async def test_arun_with_image_bytes_message_input(tmp_path):
    agent = _agent(tmp_path)

    response = await agent.arun(input=_message())

    assert response.status == RunStatus.completed
    assert response.content == "A tiny image."
    _assert_stored(agent, response.run_id)
