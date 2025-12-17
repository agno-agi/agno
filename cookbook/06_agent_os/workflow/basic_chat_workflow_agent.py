"""Example demonstrating how to add a Workflow using a WorkflowAgent to your AgentOS"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.workflow import WorkflowAgent
from agno.workflow.condition import Condition
from agno.workflow.step import Step
from agno.workflow.types import StepInput
from agno.workflow.workflow import Workflow

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"


# === AGENTS ===
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


# === CONDITION EVALUATOR ===
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


# === WORKFLOW STEPS ===
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

# === WORKFLOW WITH CONDITION ===
workflow = Workflow(
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
    db=PostgresDb(db_url),
    # debug_mode=True,
)


# Initialize the AgentOS with the workflows
agent_os = AgentOS(
    description="Example OS setup",
    workflows=[workflow],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="basic_chat_workflow_agent:app", reload=True)
