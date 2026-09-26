from pydantic import BaseModel

from agno.models.openai.chat import OpenAIChat
from agno.models.openai.like import OpenAILike


class OutputSchema(BaseModel):
    confidence: float


TOOLS = [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object", "properties": {}}}}]


def test_chat_keeps_response_format_when_tools_present_by_default():
    model = OpenAIChat(id="gpt-4.1")
    request_params = model.get_request_params(response_format=OutputSchema, tools=TOOLS)

    assert "tools" in request_params
    assert "response_format" in request_params


def test_chat_omits_response_format_when_tools_present_opt_in():
    model = OpenAIChat(id="gpt-4.1", omit_response_format_when_tools_present=True)
    request_params = model.get_request_params(response_format=OutputSchema, tools=TOOLS)

    assert "tools" in request_params
    assert "response_format" not in request_params


def test_openailike_omits_response_format_when_tools_present_opt_in():
    model = OpenAILike(id="claude-sonnet-4-5", omit_response_format_when_tools_present=True)
    request_params = model.get_request_params(response_format=OutputSchema, tools=TOOLS)

    assert "tools" in request_params
    assert "response_format" not in request_params
