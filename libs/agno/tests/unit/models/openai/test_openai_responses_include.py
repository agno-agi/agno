from agno.models.message import Message
from agno.models.openai.responses import OpenAIResponses


def test_encrypted_reasoning_include_does_not_mutate_caller_list():
    include = ["web_search_2025_01_01"]
    model = OpenAIResponses(id="gpt-5-mini", include=include, store=False)

    params = model.get_request_params(messages=[Message(role="user", content="hi")])

    assert params["include"] == ["web_search_2025_01_01", "reasoning.encrypted_content"]
    assert include == ["web_search_2025_01_01"]
