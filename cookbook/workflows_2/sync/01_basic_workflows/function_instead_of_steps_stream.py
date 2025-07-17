from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.storage.sqlite import SqliteStorage
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.utils.pprint import pprint_run_response
from agno.workflow.v2.types import WorkflowExecutionInput
from agno.workflow.v2.workflow import Workflow

# Define agents
hackernews_agent = Agent(
    name="Hackernews Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[HackerNewsTools()],
    role="Research key insights and content from Hackernews posts",
)

content_planner = Agent(
    name="Content Planner",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "Plan a content schedule over 4 weeks for the provided topic and research content",
        "Ensure that I have posts for 3 posts per week",
    ],
)


def custom_execution_function(
    workflow: Workflow, execution_input: WorkflowExecutionInput
):
    print(f"Executing workflow: {workflow.name}")

    # Run the Hackernews agent to gather research content
    research_content = ""
    for response in hackernews_agent.run(
        execution_input.message, stream=True, stream_intermediate_steps=True
    ):
        if hasattr(response, "content") and response.content:
            research_content += str(response.content)

    # Create intelligent planning prompt
    planning_prompt = f"""
        STRATEGIC CONTENT PLANNING REQUEST:

        Core Topic: {execution_input.message}

        Research Results: {research_content[:500]}

        Planning Requirements:
        1. Create a comprehensive content strategy based on the research
        2. Leverage the research findings effectively
        3. Identify content formats and channels
        4. Provide timeline and priority recommendations
        5. Include engagement and distribution strategies

        Please create a detailed, actionable content plan.
    """
    yield from content_planner.run(
        planning_prompt, stream=True, stream_intermediate_steps=True
    )


# Create and use workflow
if __name__ == "__main__":
    content_creation_workflow = Workflow(
        name="Content Creation Workflow",
        description="Automated content creation from blog posts to social media",
        storage=SqliteStorage(
            table_name="workflow_v2",
            db_file="tmp/workflow_v2.db",
            mode="workflow_v2",
        ),
        steps=custom_execution_function,
    )
    content_creation_workflow.print_response(
        message="AI trends in 2024",
        stream=True,
        stream_intermediate_steps=True,
    )
