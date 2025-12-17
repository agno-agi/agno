"""
Example showing how to use an AgentOS instance as a gateway to remote agents, teams and workflows.

Run `agent_os_setup.py` to start the remote AgentOS instance.

# Note:
- Remote Workflows via Websocket are not yet supported
- If authorization is enabled on remote servers and all endpoints are protected, not all of the functions work correctly on the gateway. Specifically /config, /workflows, /workflows/{workflow_id}, /agents, /teams, /agent/{agent_id}, /team/{team_id} need to be unprotected for the gateway to work correctly.
"""

from agno.agent import Agent, RemoteAgent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team import RemoteTeam
from agno.workflow import RemoteWorkflow, Workflow
from agno.workflow.agent import WorkflowAgent
from agno.workflow.condition import Condition
from agno.workflow.step import Step
from agno.workflow.types import StepInput

# Setup the database
db = PostgresDb(id="basic-db", db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# === SETUP ADVANCED WORKFLOW ===
story_writer = Agent(
    name="Story Writer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are tasked with writing a 100 word story based on a given topic",
)

story_editor = Agent(
    name="Story Editor",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Review and improve the story's grammar, flow, and clarity",
)

story_formatter = Agent(
    name="Story Formatter",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Break down the story into prologue, body, and epilogue sections",
)


def needs_editing(step_input: StepInput) -> bool:
    """Determine if the story needs editing based on length and complexity"""
    story = step_input.previous_step_content or ""

    # Check if story is long enough to benefit from editing
    word_count = len(story.split())

    # Edit if story is more than 50 words or contains complex punctuation
    return word_count > 50 or any(punct in story for punct in ["!", "?", ";", ":"])


def add_references(step_input: StepInput):
    """Add references to the story"""
    previous_output = step_input.previous_step_content

    if isinstance(previous_output, str):
        return previous_output + "\n\nReferences: https://www.agno.com"


write_step = Step(
    name="write_story",
    description="Write initial story",
    agent=story_writer,
)

edit_step = Step(
    name="edit_story",
    description="Edit and improve the story",
    agent=story_editor,
)

format_step = Step(
    name="format_story",
    description="Format the story into sections",
    agent=story_formatter,
)

# Create a WorkflowAgent that will decide when to run the workflow
workflow_agent = WorkflowAgent(model=OpenAIChat(id="gpt-4o-mini"), num_history_runs=4)

advanced_workflow = Workflow(
    name="Story Generation with Conditional Editing",
    description="A workflow that generates stories, conditionally edits them, formats them, and adds references",
    agent=workflow_agent,
    steps=[
        write_step,
        Condition(
            name="editing_condition",
            description="Check if story needs editing",
            evaluator=needs_editing,
            steps=[edit_step],
        ),
        format_step,
        add_references,
    ],
    db=db,
)

# Setup our AgentOS app
agent_os = AgentOS(
    description="Example app for basic agent, team and workflow",
    agents=[
        RemoteAgent(base_url="http://localhost:7778", agent_id="assistant-agent"),
        RemoteAgent(base_url="http://localhost:7778", agent_id="researcher-agent"),
    ],
    teams=[RemoteTeam(base_url="http://localhost:7778", team_id="research-team")],
    workflows=[
        RemoteWorkflow(base_url="http://localhost:7778", workflow_id="qa-workflow"),
        advanced_workflow,
    ],
)
app = agent_os.get_app()


if __name__ == "__main__":
    """
    Run your AgentOS.
    """
    agent_os.serve(app="03_agent_os_gateway:app", reload=True, port=7777)
