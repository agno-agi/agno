"""Approve or reject a side-effecting tool without API keys or network access.

The local model deterministically requests the same simulated email tool on each
run. The first scenario rejects the request; the second approves it. Assertions
verify that only the approved request reaches the simulated outbox.
"""

import json
from typing import Any, AsyncIterator, Dict, Iterator, List

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.run.base import RunStatus
from agno.tools import tool

SIMULATED_OUTBOX: List[Dict[str, str]] = []
SIMULATED_APPROVAL_LOG: List[Dict[str, str]] = []


class DeterministicApprovalModel(Model):
    """Return one tool call followed by a final response, entirely offline."""

    def __init__(self) -> None:
        super().__init__(
            id="deterministic-approval-demo",
            name="Deterministic approval demo",
            provider="local",
        )
        self._turn = 0

    def _next_response(self) -> ModelResponse:
        self._turn += 1
        if self._turn == 1:
            response = ModelResponse(role="assistant")
            response.tool_calls = [
                {
                    "id": "send-welcome-email",
                    "type": "function",
                    "function": {
                        "name": "send_email",
                        "arguments": json.dumps(
                            {
                                "recipient": "customer@example.com",
                                "subject": "Welcome",
                                "body": "Thanks for joining us.",
                            }
                        ),
                    },
                }
            ]
            return response

        response = ModelResponse(
            content="The approval decision was processed.", role="assistant"
        )
        response.event = ModelResponseEvent.assistant_response.value
        return response

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next_response()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next_response()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._next_response()

    async def ainvoke_stream(
        self, *args: Any, **kwargs: Any
    ) -> AsyncIterator[ModelResponse]:
        yield self._next_response()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()


@tool(requires_confirmation=True)
def send_email(recipient: str, subject: str, body: str) -> str:
    """Add an email to a simulated outbox.

    Args:
        recipient: Email address that should receive the message.
        subject: Subject line for the email.
        body: Body of the email.
    """
    SIMULATED_OUTBOX.append({"recipient": recipient, "subject": subject, "body": body})
    return f"Email queued for {recipient}"


def run_scenario(approve: bool) -> None:
    """Run one isolated approval scenario and verify its side effect."""
    SIMULATED_OUTBOX.clear()
    SIMULATED_APPROVAL_LOG.clear()

    agent = Agent(
        model=DeterministicApprovalModel(),
        tools=[send_email],
        db=SqliteDb(db_file="tmp/side_effect_tool_approval.db"),
        telemetry=False,
    )
    paused_response = agent.run("Send the customer a welcome email.")

    if paused_response.status != RunStatus.paused:
        raise RuntimeError("Expected the run to pause for confirmation")
    if SIMULATED_OUTBOX:
        raise RuntimeError("The side effect happened before approval")

    requirements = list(paused_response.active_requirements)
    if len(requirements) != 1 or not requirements[0].needs_confirmation:
        raise RuntimeError("Expected exactly one confirmation requirement")

    requirement = requirements[0]
    tool_execution = requirement.tool_execution
    if tool_execution is None:
        raise RuntimeError("The confirmation requirement has no tool execution")

    decision = "approved" if approve else "rejected"

    # Replace this in-memory list with durable application storage. Record the
    # authenticated actor, decision, tool arguments, and timestamp before resume.
    SIMULATED_APPROVAL_LOG.append(
        {
            "actor": "demo-user",
            "decision": decision,
            "tool": tool_execution.tool_name or "unknown",
            "arguments": json.dumps(tool_execution.tool_args or {}, sort_keys=True),
        }
    )

    if approve:
        requirement.confirm()
    else:
        requirement.reject(note="Rejected by demo-user")

    final_response = agent.continue_run(
        run_id=paused_response.run_id,
        requirements=paused_response.requirements,
    )

    if final_response.status != RunStatus.completed:
        raise RuntimeError("Expected the resumed run to complete")

    expected_outbox_size = 1 if approve else 0
    if len(SIMULATED_OUTBOX) != expected_outbox_size:
        raise RuntimeError("The side effect did not match the approval decision")
    if SIMULATED_APPROVAL_LOG[0]["decision"] != decision:
        raise RuntimeError("The approval decision was not recorded")

    print(f"Decision: {decision}")
    print(f"Outbox entries: {len(SIMULATED_OUTBOX)}")
    print(f"Final status: {final_response.status.value}")


if __name__ == "__main__":
    run_scenario(approve=False)
    run_scenario(approve=True)
