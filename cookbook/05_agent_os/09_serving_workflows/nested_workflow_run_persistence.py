"""
Reproduce Nested Workflow Run Persistence
=========================================

Serve a database-backed Workflow whose final Agent and Team executors are
inside a Steps container. This reproduces the regression where nested
executors do not receive the Workflow ID and persist as standalone runs.

Before the fix, repeated Studio runs may show nested Agent/Team outputs as
separate top-level messages, or persisted history may contain only the nested
executor runs instead of the Workflow run. After the fix, each submission
should persist and render as one Workflow run with embedded executor runs.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/09_serving_workflows/nested_workflow_run_persistence.py

Then connect Studio to http://localhost:7777, select
``nested-workflow-run-persistence``, send the same prompt several times, and
reload the session after each run.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.team import Team
from agno.workflow import Step, Steps, Workflow

# ---------------------------------------------------------------------------
# Create Served Workflow
# ---------------------------------------------------------------------------

WORKFLOW_ID = "nested-workflow-run-persistence"

db = SqliteDb(
    id="nested-workflow-run-persistence-db",
    db_file="tmp/nested_workflow_run_persistence.db",
)

research_agent = Agent(
    id="nested-workflow-researcher",
    name="Nested Workflow Researcher",
    role="Collect the key facts for a topic",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="Collect the key facts for the topic in a concise brief.",
)

draft_agent = Agent(
    id="nested-workflow-drafter",
    name="Nested Workflow Drafter",
    role="Turn research notes into a short draft",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="Turn the preceding research into a concise draft.",
)

fact_checker = Agent(
    id="nested-workflow-fact-checker",
    name="Nested Workflow Fact Checker",
    role="Check the draft for factual consistency",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="Check the preceding draft and identify factual issues.",
)

editor = Agent(
    id="nested-workflow-editor",
    name="Nested Workflow Editor",
    role="Produce the final reviewed response",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="Return a concise final response incorporating the review.",
)

review_team = Team(
    id="nested-workflow-review-team",
    name="Nested Workflow Review Team",
    members=[fact_checker, editor],
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="Review the draft and return one polished final response.",
)

nested_workflow = Workflow(
    id=WORKFLOW_ID,
    name="Nested Workflow Run Persistence",
    description="Reproduce persistence behavior for nested Agent and Team steps",
    db=db,
    steps=[
        Step(
            name="Initial Research",
            agent=research_agent,
            description="Collect the initial facts for the topic",
        ),
        Steps(
            name="Nested Draft and Review",
            steps=[
                Step(
                    name="Draft Response",
                    agent=draft_agent,
                    description="Draft a response from the initial research",
                ),
                Step(
                    name="Review Response",
                    team=review_team,
                    description="Review and improve the drafted response",
                ),
            ],
        ),
    ],
)

agent_os = AgentOS(
    id="nested-workflow-run-persistence-os",
    description="AgentOS reproduction for nested Workflow run persistence.",
    agents=[research_agent, draft_agent],
    teams=[review_team],
    workflows=[nested_workflow],
    db=db,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Workflow Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Nested workflow persistence AgentOS on http://localhost:7777")
    agent_os.serve(app=app, port=7777)
