"""
Workflow With Workflow as a Step
================================

Demonstrates deeply nested workflows (3 levels) with a Parallel step containing
a Condition, all served via AgentOS.

Architecture:
  Level 1 (Outer):  "Research and Write"
  +-- research_phase (Level 2 workflow)
  |   +-- Parallel:
  |   |   +-- branch_a: Level 3 workflow "Data Collection"
  |   |   |             +-- gather (agent)
  |   |   |             +-- analyze (agent)
  |   |   +-- branch_b: Condition "fact_check_gate"
  |   |                 +-- if numbers present: fact_check (agent)
  |   |                 +-- else:               pass_through (function)
  |   +-- merge (function)
  +-- writing_phase (agent)
"""

from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------
from agno.os import AgentOS
from agno.tools.websearch import WebSearchTools
from agno.workflow.condition import Condition
from agno.workflow.parallel import Parallel
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow

# Database connection
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")


# === HELPER FUNCTIONS ===


def needs_fact_check(step_input: StepInput) -> bool:
    """Check if the research contains numbers or statistics that need verification."""
    prev = step_input.previous_step_content or step_input.input or ""
    return any(char.isdigit() for char in prev)


def pass_through(step_input: StepInput) -> StepOutput:
    """Pass content through when fact-checking is not needed."""
    prev = step_input.previous_step_content or step_input.input
    return StepOutput(content=prev)


def merge_parallel_results(step_input: StepInput) -> StepOutput:
    """Merge the outputs from the parallel data-collection and fact-check branches."""
    prev = step_input.previous_step_content or ""
    return StepOutput(content=f"Combined research:\n{prev}")


# === AGENTS ===

data_gatherer = Agent(
    name="Data Gatherer",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions="Gather raw data, statistics, and concrete facts on the topic. Be concise (2-3 sentences).",
    tools=[WebSearchTools()],
)

data_analyzer = Agent(
    name="Data Analyzer",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions="Analyze the gathered data. Identify key trends and insights. Be concise (2-3 sentences).",
)

fact_checker = Agent(
    name="Fact Checker",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions="Verify the facts in the provided text. Correct any inaccuracies and note confidence levels.",
    tools=[WebSearchTools()],
)

writer = Agent(
    name="Writer",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions="Write a polished, well-structured article from the research provided. Use clear headings and concise paragraphs.",
)

# === LEVEL 3 (innermost) WORKFLOW: Data Collection ===

data_collection_workflow = Workflow(
    name="Data Collection",
    description="Gathers raw data and then analyzes it",
    steps=[
        Step(name="gather", agent=data_gatherer, description="Gather raw data"),
        Step(name="analyze", agent=data_analyzer, description="Analyze the gathered data"),
    ],
)

# === LEVEL 2 WORKFLOW: Research with Parallel Data Collection + Conditional Fact Check ===

inner_workflow = Workflow(
    name="Research with Fact Check",
    description="Runs data collection and conditional fact-checking in parallel, then merges",
    steps=[
        Parallel(
            Step(
                name="data_branch",
                workflow=data_collection_workflow,
                description="Run the data-collection sub-workflow",
            ),
            Condition(
                name="fact_check_gate",
                description="Fact-check if the topic likely contains numbers or statistics",
                evaluator=needs_fact_check,
                steps=[Step(name="fact_check", agent=fact_checker, description="Verify facts and claims")],
                else_steps=[Step(name="pass_through", executor=pass_through, description="Pass topic through")],
            ),
            name="parallel_research",
            description="Collect data and fact-check in parallel",
        ),
        Step(name="merge", executor=merge_parallel_results, description="Merge parallel research outputs"),
    ],
)

# === LEVEL 1 (outer) WORKFLOW: uses inner workflow as a step, then writes ===

outer_workflow = Workflow(
    name="Research and Write",
    description="Researches a topic (with parallel data collection and fact-checking), then writes a polished article",
    steps=[
        Step(name="research_phase", workflow=inner_workflow, description="Run the research sub-workflow"),
        Step(name="writing_phase", agent=writer, description="Write the final article"),
    ],
    db=db,
)

# Initialize the AgentOS with the workflow
agent_os = AgentOS(
    description="Deeply nested workflow demo: 3 levels with Parallel + Condition, served via AgentOS",
    workflows=[outer_workflow],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Example prompt:
    #   "What are the key milestones in space exploration?"
    agent_os.serve(app="workflow_with_workflow_as_step:app", reload=True)
