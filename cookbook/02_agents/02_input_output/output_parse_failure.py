"""
Output Parse Failure
===================

Fail a run explicitly when its reply cannot be converted to the requested
Pydantic output. The default remains warning-only. This option is ignored when
parse_response=False and does not validate dictionary JSON schemas or trigger
provider fallback. Configured run retries still apply.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.run import RunStatus
from agno.run.agent import RunErrorEvent
from pydantic import BaseModel


class Ticket(BaseModel):
    category: str
    priority: int


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    output_schema=Ticket,
    fail_on_output_parse_error=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    result = agent.run("Classify: the printer on floor 3 is jammed.")
    if result.status == RunStatus.error:
        for event in result.events or []:
            if (
                isinstance(event, RunErrorEvent)
                and event.error_type == "output_parse_error"
            ):
                print(event.content)
    else:
        print(result.content)

    # Team accepts the same setting. With stream=True, consume RunErrorEvent
    # (TeamRunErrorEvent for Team); a failed parse does not emit RunCompleted.
