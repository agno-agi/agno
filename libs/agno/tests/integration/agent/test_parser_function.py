from agno.agent import Agent


def test_parser_function_sync_no_response_model(monkeypatch):
    # Main model returns some free-form text; parser_function reformats it
    class DummyModel:
        def __init__(self, id: str = "dummy"):
            self.id = id
            self.name = "DummyModel"
            self.provider = "dummy"
            self.assistant_message_role = "assistant"
            self.supports_native_structured_outputs = False
            self.supports_json_schema_outputs = False

        def get_instructions_for_model(self, tools=None):
            return None

        def get_system_message_for_model(self, tools=None):
            return None

        def response(self, messages, tools=None, functions=None, tool_choice=None, tool_call_limit=None, response_format=None):
            from agno.models.response import ModelResponse

            return ModelResponse(content="Title: Yosemite; Activities: Hiking, Camping")

    def my_parser(text: str):
        # Minimal transform; in real life this could parse to any shape
        return {"title": "Yosemite", "activities": ["Hiking", "Camping"]}

    agent = Agent(model=DummyModel(), parser_function=my_parser)

    resp = agent.run("Tell me about Yosemite")
    assert isinstance(resp.content, dict)
    assert resp.content["title"] == "Yosemite"
    assert resp.content["activities"] == ["Hiking", "Camping"]


def test_parser_function_conflicts_raise():
    class DummyModel:
        def __init__(self, id: str = "dummy"):
            self.id = id
            self.name = "DummyModel"
            self.provider = "dummy"
            self.assistant_message_role = "assistant"
            self.supports_native_structured_outputs = False
            self.supports_json_schema_outputs = False

        def get_instructions_for_model(self, tools=None):
            return None

        def get_system_message_for_model(self, tools=None):
            return None

        def response(self, messages, tools=None, functions=None, tool_choice=None, tool_call_limit=None, response_format=None):
            from agno.models.response import ModelResponse

            return ModelResponse(content="anything")

    def my_parser(text: str):
        return {"ok": True}

    from pydantic import BaseModel

    class R(BaseModel):
        ok: bool

    # parser_function must not be combined with response_model or parser_model
    try:
        Agent(model=DummyModel(), parser_function=my_parser, response_model=R)
        assert False, "Expected ValueError for parser_function + response_model"
    except ValueError:
        pass

    # parser_model conflict
    class DummyParserModel(DummyModel):
        pass

    try:
        Agent(model=DummyModel(), parser_function=my_parser, parser_model=DummyParserModel())
        assert False, "Expected ValueError for parser_function + parser_model"
    except ValueError:
        pass
