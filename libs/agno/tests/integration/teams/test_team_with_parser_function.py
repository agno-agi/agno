from agno.team import Team


def test_team_parser_function_sync_no_response_model():
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

        def response(
            self,
            messages,
            tools=None,
            functions=None,
            response_format=None,
            tool_choice=None,
            tool_call_limit=None,
        ):
            from agno.models.response import ModelResponse

            return ModelResponse(content="Los Angeles Itinerary: Beach, Museum, Tacos")

    def my_parser(text: str):
        return {"city": "Los Angeles", "plan": ["Beach", "Museum", "Tacos"]}

    team = Team(members=[], model=DummyModel(), parser_function=my_parser)

    resp = team.run("Make an itinerary for LA")
    assert isinstance(resp.content, dict)
    assert resp.content["city"] == "Los Angeles"
    assert resp.content["plan"] == ["Beach", "Museum", "Tacos"]
