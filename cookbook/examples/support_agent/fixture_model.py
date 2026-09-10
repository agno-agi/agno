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
    ("search_knowledge_base", {"query": "Lantern workspace export"}),
    {
        "status": "answered",
        "answer": "Owners and admins export from Settings > Data > Export.",
        "sources": ["docs/exports.md"],
        "handoff": None,
    },
    ("search_knowledge_base", {"query": "member workspace export permission"}),
    {
        "status": "answered",
        "answer": "Members cannot export; ask the owner to change your role.",
        "sources": ["docs/exports.md", "docs/membership.md"],
        "handoff": None,
    },
    (
        "search_knowledge_base",
        {"query": "Germany export hosting custom contract guarantee"},
    ),
    {
        "status": "needs_human",
        "answer": "The docs do not establish a Germany hosting guarantee. This handoff is local.",
        "sources": [],
        "handoff": {
            "question": "Can you guarantee my exported data stays in Germany under a custom contract?",
            "relevant_context": "The user wants workspace exports and asked about member permissions.",
            "unresolved": ["Germany data residency and custom contract terms"],
        },
    },
]
