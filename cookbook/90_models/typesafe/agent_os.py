"""Serve Jev classification and routing with AgentOS.

Ticket Classifier returns typed decisions. Support Router uses Jev to select
one specialist, whose generative model writes the response.

Setup: pip install -e "libs/agno[typesafe,openai,os]"
Set TYPESAFE_API_KEY and OPENAI_API_KEY (the classifier only needs TypeSafe).
Run: python cookbook/90_models/typesafe/agent_os.py
Inspect: http://localhost:7777/docs or http://localhost:7777/config
Connect: https://os.agno.com using http://localhost:7777 as the endpoint.

Try each department in either component:
- "I was charged twice for my subscription. Please refund the duplicate."
- "Our workspace returns a 500 error. Nobody can log in and all work is blocked."

SQLite stores local demo sessions. Use PostgreSQL for production.
"""

from typing import Annotated, Literal

from pydantic import BaseModel
from typesafe_sdk import Choice, Noul

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.models.typesafe import Jev, JevField
from agno.os import AgentOS
from agno.team import Team
from agno.team.mode import TeamMode


class Triage(BaseModel):
    department: Annotated[
        Literal["billing", "technical"],
        JevField(
            Choice(
                instructions="Which department should handle the request in state.input?",
                criteria={
                    "billing": "Payments, duplicate charges, subscriptions and refunds",
                    "technical": "Bugs, outages, login failures and configuration",
                },
            )
        ),
    ]
    urgent: Annotated[
        bool,
        JevField(
            Noul(
                instructions="Does state.input describe work that is completely blocked?"
            ),
            threshold=0.8,
        ),
    ]


db = SqliteDb(id="jev-demo-db", db_file="tmp/jev_agent_os.db")

classifier = Agent(
    id="ticket-classifier",
    name="Ticket Classifier",
    description="Classify a ticket by department and urgency using Jev.",
    model=Jev(),
    output_schema=Triage,
    db=db,
)

billing = Agent(
    id="billing",
    name="Billing",
    role="Handle payment, subscription and refund questions",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    instructions="Suggest the next steps for the billing issue briefly. Do not claim to have issued refunds or changed an account.",
)
technical = Agent(
    id="technical",
    name="Technical Support",
    role="Handle outages, bugs, login failures and configuration issues",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    instructions="Suggest concise troubleshooting steps for the technical issue.",
)

support_team = Team(
    id="support-router",
    name="Support Router",
    description="Jev routes each request to one specialist who writes the answer.",
    model=Jev(mode="route"),
    mode=TeamMode.route,
    determine_input_for_members=False,
    members=[billing, technical],
    instructions="Route charges, subscriptions and refunds to Billing. Route bugs, outages and login failures to Technical Support.",
    db=db,
    markdown=True,
)

agent_os = AgentOS(
    id="jev-agent-os",
    description="Jev classifies and routes; generative specialists answer.",
    agents=[classifier],
    teams=[support_team],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="agent_os:app", reload=True)
