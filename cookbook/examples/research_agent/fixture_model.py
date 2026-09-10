"""Offline scripted model for this example's deterministic fixture demonstration.
This exercises Agent and tool execution; it does not evaluate a language model.
"""

import json

from agno.metrics import MessageMetrics
from agno.models.base import Model
from agno.models.response import ModelResponse


class FixtureModel(Model):
    def __init__(self, turns):
        super().__init__(id="fixture", name="Fixture", provider="local")
        self.turns = iter(turns)

    def invoke(self, *args, **kwargs):
        turn = next(self.turns)
        response = ModelResponse(role="assistant", response_usage=MessageMetrics())
        if isinstance(turn, tuple):
            name, arguments = turn
            response.tool_calls = [
                {
                    "id": "fixture-call",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                }
            ]
        else:
            response.content = json.dumps(turn)
        return response

    async def ainvoke(self, *args, **kwargs):
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response, **kwargs):
        return response


# ---------------------------------------------------------------------------
# Create the deterministic source inspection and answer sequence
# ---------------------------------------------------------------------------
def fixture_model():
    return FixtureModel(TURNS)


TURNS = [
    ("search_sources", {"query": "library repair cafe pilot"}),
    ("read_source", {"url": "https://library.example/pilot"}),
    ("read_source", {"url": "https://community.example/survey"}),
    {
        "question": "Should a small public library pilot a monthly repair cafe?",
        "findings": [
            {
                "finding": "The fictional pilot repaired 18 of 30 items; it suggests a bounded pilot could help.",
                "sources": ["https://library.example/pilot"],
            },
            {
                "finding": "The fictional survey found limited volunteer capacity.",
                "sources": ["https://community.example/survey"],
            },
        ],
        "uncertainty": [
            "Monthly and quarterly recommendations differ; both samples are small."
        ],
        "open_questions": [
            "Are trained volunteers and safe testing equipment available?"
        ],
    },
]
