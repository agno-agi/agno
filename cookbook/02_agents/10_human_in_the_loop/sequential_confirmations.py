"""Present a scripted batch of confirmations one at a time, without API keys.

The local model implements only synchronous, non-streaming responses.
"""

from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.message import Message
from agno.models.openai import OpenAIResponses
from agno.models.response import ModelResponse, ToolExecution
from agno.run import RunContext
from agno.tools import tool

executed: list[str] = []


@tool(requires_confirmation=True)
def approve_report() -> str:
    """Approve the report for publication."""
    executed.append("approve_report")
    return "Report approved."


@tool(requires_confirmation=True)
def publish_report() -> str:
    """Publish the approved report."""
    executed.append("publish_report")
    return "Report published."


class ScriptedBatch(OpenAIResponses):
    """Return two calls together, then check their results without network access."""

    def __init__(self) -> None:
        super().__init__(id="gpt-5.5")
        self.calls = 0

    def invoke(self, messages: list[Message], **kwargs: Any) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": name,
                        "type": "function",
                        "function": {"name": name, "arguments": "{}"},
                    }
                    for name in ("publish_report", "approve_report")
                ],
            )
        result_ids = [m.tool_call_id for m in messages if m.role == "tool"]
        assert Counter(result_ids) == Counter(["publish_report", "approve_report"])
        return ModelResponse(role="assistant", content="Both confirmations completed.")

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response


def approval_first(pending: list[ToolExecution], _context: RunContext) -> list[str]:
    ordered = sorted(pending, key=lambda call: call.tool_name != "approve_report")
    return [call.tool_call_id for call in ordered if call.tool_call_id is not None]


if __name__ == "__main__":
    with TemporaryDirectory() as directory:
        model = ScriptedBatch()
        agent = Agent(
            model=model,
            tools=[approve_report, publish_report],
            db=SqliteDb(db_file=str(Path(directory) / "confirmations.db")),
            sequential_tool_confirmations=True,
            confirmation_policy=approval_first,
            telemetry=False,
        )
        response = agent.run("Approve and publish the report.")
        assert executed == [] and model.calls == 1

        for index, name in enumerate(("approve_report", "publish_report")):
            assert response.is_paused and len(response.active_requirements) == 1
            requirement = response.active_requirements[0]
            assert requirement.tool_execution.tool_name == name
            assert model.calls == 1
            print("Confirming:", name)
            requirement.confirm()
            response = agent.continue_run(
                run_id=response.run_id, requirements=response.requirements
            )
            assert executed == ["approve_report", "publish_report"][: index + 1]

        assert not response.is_paused and model.calls == 2
        print("Model calls:", model.calls)
        print(response.content)
