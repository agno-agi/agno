"""
Broadcast Mode With a Jev Judge
===============================

Demonstrates `mode=broadcast` with Jev, TypeSafe's System One model, as the team leader.

Broadcast normally ends with the leader writing a synthesis. Jev does not write text, so it
does the other thing a panel needs: it judges. The request goes to every member unchanged,
and Jev then fills the team's `output_schema` from their replies - which reply is best, whether
the panel agrees, how strong the case is.

Jev makes one judgment call for the whole panel. Each member needs its own generative model.

Requirements:
- `pip install typesafe-sdk openai` (Python 3.10+)
- export TYPESAFE_API_KEY="your_api_key"
- export OPENAI_API_KEY="your_api_key"
"""

import json
from enum import IntEnum
from typing import Literal

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.models.typesafe import Jev
from agno.team.mode import TeamMode
from agno.team.team import Team
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Define the Verdict
# ---------------------------------------------------------------------------


class Strength(IntEnum):
    weak = 0
    moderate = 1
    strong = 2


class Verdict(BaseModel):
    recommendation: Literal["adopt", "trial", "reject"] = Field(
        description="Taking the replies in `results` together, what should the company do with the proposal in `request`?",
        json_schema_extra={
            "criteria": {
                "adopt": "The replies support rolling it out now",
                "trial": "The replies support a limited pilot before deciding",
                "reject": "The replies advise against it",
            }
        },
    )
    panel_agrees: bool = Field(
        description="Do the replies in `results` reach the same overall conclusion?"
    )
    risk_raised: bool = Field(
        description="Does any reply in `results` raise a legal, security or compliance risk?"
    )
    case_strength: Strength = Field(
        description="How strong is the combined case made by the replies in `results`?",
        json_schema_extra={
            "criteria": [
                "Mostly opinion, few concrete reasons",
                "Some concrete reasons, with gaps",
                "Concrete reasons that address costs, benefits and risks",
            ]
        },
    )


# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------

finance_agent = Agent(
    name="Finance Reviewer",
    role="Judges proposals on cost and return",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    instructions=["Give your view in three sentences, from a finance perspective."],
)

security_agent = Agent(
    name="Security Reviewer",
    role="Judges proposals on security and compliance risk",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    instructions=["Give your view in three sentences, from a security perspective."],
)

people_agent = Agent(
    name="People Reviewer",
    role="Judges proposals on their effect on employees",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    instructions=["Give your view in three sentences, from a people perspective."],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------

team = Team(
    name="Review Panel",
    mode=TeamMode.broadcast,
    model=Jev(),
    members=[finance_agent, security_agent, people_agent],
    output_schema=Verdict,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run = team.run(
        "Proposal: let every employee use personal AI coding assistants on company source code, starting next month."
    )

    verdict: Verdict = run.content
    print("recommendation:", verdict.recommendation)
    print("panel agrees:  ", verdict.panel_agrees)
    print("risk raised:   ", verdict.risk_raised)
    print("case strength: ", verdict.case_strength.name)

    print("\nWhat the members said:")
    for member_run in run.member_responses:
        print(f"- {member_run.agent_name}: {str(member_run.content)[:220]}")

    print("\nWhat Jev decided:")
    print(json.dumps((run.model_provider_data or {}).get("answers"), indent=2))
