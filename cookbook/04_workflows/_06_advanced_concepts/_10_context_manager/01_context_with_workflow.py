"""Use context items with Workflows."""

from agno.agent import Agent
from agno.context.manager import ContextManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

db = SqliteDb(db_file="tmp/context.db", context_table="context_items")
context_manager = ContextManager(db=db)

# Create context with variables
workflow_template = """You are analyzing {topic} to produce {output_type}.
Focus on {focus_areas} and ensure the output is {quality_standard}."""

context_manager.create(
    name="workflow_template",
    content=workflow_template,
    description="Workflow instruction template",
)

# Create agent with context
analyst = Agent(
    name="Analyst",
    model=OpenAIChat(id="gpt-4o"),
    system_message=context_manager.get(
        name="workflow_template",
        topic="database options for AI agents",
        output_type="a comparative analysis",
        focus_areas="performance, ease of use, and scalability",
        quality_standard="thorough and actionable",
    ),
    debug_mode=True,
)

# Create workflow with agent
analysis_step = Step(name="Analysis", agent=analyst)

workflow = Workflow(
    name="Analysis Workflow",
    db=db,
    steps=[analysis_step],
)

# Run workflow
result = workflow.run(input="Compare SQLite vs PostgreSQL for AI agents")
print(result.content)
