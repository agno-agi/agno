from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.storage.postgres import PostgresStorage
from agno.workflow.v2.step import ChatStep, Step
from agno.workflow.v2.workflow import Workflow

# =============================================================================
# Agents
# =============================================================================

# Sample report agent for testing, would be replaced by a series of agents for gathering, analyzing, writing and formatting the report
report_agent = Agent(
    name="Report Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="""
    You are tasked with generating a detailed report on the topic of the user's query.

    <Rules> 
    The report should be:
    - Detailed and include all relevant information.
    - Comprehensive
    - Offer well rounded understanding of the topic
    - Include relevant examples and references
    </Rules>
    """,
)

# =============================================================================
# Workflow Definition
# =============================================================================

chat_workflow = Workflow(
    name="Report Generator Workflow",
    description="Interactive report generator workflow",
    steps=[Step(name="report", agent=report_agent)],
    chat_step=ChatStep(
        final_step="report",
    ),
    storage=PostgresStorage(
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        table_name="chat_workflow",
        mode="workflow_v2",
    ),
)


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    chat_workflow.cli_app(user="You", emoji="💬", stream=False, markdown=True)
