import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.storage.sqlite import SqliteStorage
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.workflow.v2.task import Task, TaskInput, TaskOutput
from agno.workflow.v2.workflow import Workflow

# Define agents
hackernews_agent = Agent(
    name="Hackernews Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[HackerNewsTools()],
    instructions="Extract key insights and content from Hackernews posts",
)

web_agent = Agent(
    name="Web Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    instructions="Search the web for the latest news and trends",
)

# Define research team for complex analysis
research_team = Team(
    name="Research Team",
    mode="coordinate",
    members=[hackernews_agent, web_agent],
    instructions="Analyze content and create comprehensive social media strategy",
)

content_planner = Agent(
    name="Content Planner",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "Plan a content schedule over 4 weeks for the provided topic and research content",
        "Ensure that I have posts for 3 posts per week",
    ],
)


async def custom_content_planning_function(task_input: TaskInput) -> TaskOutput:
    """
    Custom function that does intelligent content planning with context awareness
    """
    message = task_input.message
    previous_task_content = task_input.previous_task_content

    # Create intelligent planning prompt
    planning_prompt = f"""
        STRATEGIC CONTENT PLANNING REQUEST:

        Core Topic: {message}

        Research Results: {previous_task_content[:500] if previous_task_content else "No research results"}

        Planning Requirements:
        1. Create a comprehensive content strategy based on the research
        2. Leverage the research findings effectively
        3. Identify content formats and channels
        4. Provide timeline and priority recommendations
        5. Include engagement and distribution strategies

        Please create a detailed, actionable content plan.
    """

    try:
        response_iterator = await content_planner.arun(planning_prompt, stream=True, stream_intermediate_steps=True)
        for event in response_iterator:
            yield event

        response = content_planner.run_response

        enhanced_content = f"""
            ## Strategic Content Plan

            **Planning Topic:** {message}

            **Research Integration:** {"✓ Research-based" if previous_task_content else "✗ No research foundation"}

            **Content Strategy:**
            {response.content}

            **Custom Planning Enhancements:**
            - Research Integration: {"High" if previous_task_content else "Baseline"}
            - Strategic Alignment: Optimized for multi-channel distribution
            - Execution Ready: Detailed action items included
        """.strip()

        yield TaskOutput(
            content=enhanced_content,
            response=response
        )

    except Exception as e:
        yield TaskOutput(
            content=f"Custom content planning failed: {str(e)}",
            success=False,
        )


# Define tasks using different executor types

research_task = Task(
    name="Research Task",
    team=research_team,
)

content_planning_task = Task(
    name="Content Planning Task",
    executor=custom_content_planning_function,
)

async def main():
    content_creation_workflow = Workflow(
        name="Content Creation Workflow",
        description="Automated content creation with custom execution options",
        storage=SqliteStorage(
            table_name="workflow_v2",
            db_file="tmp/workflow_v2.db",
            mode="workflow_v2",
        ),
        tasks=[research_task, content_planning_task],
    )
    print("=== Custom Sequence (Custom Execution Functions) ===")
    try:
        await content_creation_workflow.aprint_response(
            message="AI agent frameworks 2025",
            markdown=True,
            stream=True,
            stream_intermediate_steps=True,
        )
    except Exception as e:
        print(f"Custom workflow failed: {e}")

    print("\n" + "=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
