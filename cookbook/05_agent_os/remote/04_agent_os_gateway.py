"""
Example showing how to use an AgentOS instance as a gateway to remote agents, teams and workflows.

The gateway combines entities from a remote AgentOS (consumed through its
RemoteAccess interface) with local agents and workflows, all served on a single API.

Prerequisites:
1. Start the backing server:
   python cookbook/05_agent_os/remote/server.py

   The server will run on http://localhost:7778

2. Set your OPENAI_API_KEY environment variable

Notes:
- Workflows are not remotely executable, so the gateway only serves its local workflow.
- The RemoteAccess interface serves execution and entity metadata. Session, memory, and
  knowledge proxies still use the remote server's main API, so those routes must be
  reachable for the gateway db features to work.
"""

from agno.agent import Agent, RemoteAgent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.team import RemoteTeam
from agno.workflow import Workflow
from agno.workflow.condition import Condition
from agno.workflow.step import Step
from agno.workflow.types import StepInput

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

# Setup the database
db = SqliteDb(id="gateway-db", db_file="tmp/remote_gateway.db")

# === SETUP LOCAL WORKFLOW ===
story_writer = Agent(
    name="Story Writer",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="You are tasked with writing a 100 word story based on a given topic",
)

story_editor = Agent(
    name="Story Editor",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="Review and improve the story's grammar, flow, and clarity",
)

story_formatter = Agent(
    name="Story Formatter",
    model=OpenAIResponses(id="gpt-5.5"),
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

story_workflow = Workflow(
    name="Story Generation with Conditional Editing",
    description="A workflow that generates stories, conditionally edits them, formats them, and adds references",
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
    description="Gateway combining remote and local agents, teams, and workflows",
    agents=[
        # Remote agents consumed through the RemoteAccess interface of server.py
        RemoteAgent(base_url="http://localhost:7778", agent_id="assistant-agent"),
        RemoteAgent(base_url="http://localhost:7778", agent_id="researcher-agent"),
        # Local agents
        story_writer,
        story_editor,
        story_formatter,
    ],
    teams=[RemoteTeam(base_url="http://localhost:7778", team_id="research-team")],
    workflows=[story_workflow],
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """
    Run your AgentOS gateway.

    This gateway combines:
    - Remote agents and a remote team (from port 7778)
    - Local agents and a local workflow

    All accessible via a single API on port 7777.
    """
    agent_os.serve(app="04_agent_os_gateway:app", reload=True, port=7777)
