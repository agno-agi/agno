import asyncio
from typing import AsyncIterator, Union

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.v2.workflow import TaskErrorEvent, WorkflowRunResponseEvent
from agno.storage.sqlite import SqliteStorage
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.workflow.v2.task import Task, TaskInput, TaskOutput
from agno.workflow.v2.workflow import Workflow

# Define agents
blog_analyzer = Agent(
    name="Blog Analyzer",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    instructions="Extract key insights and content from blog posts",
)

content_planner = Agent(
    name="Content Planner",
    model=OpenAIChat(id="gpt-4o"),
    instructions="Create engaging social media content plans based on analysis",
)

# Define research team for complex analysis
research_team = Team(
    name="Research Team",
    mode="coordinate",
    members=[blog_analyzer, content_planner],
    instructions="Analyze content and create comprehensive social media strategy",
)


# Updated custom execution functions that work with TaskInput
async def streaming_blog_analysis_function(
    task_input: TaskInput,
) -> AsyncIterator[Union[WorkflowRunResponseEvent, TaskOutput]]:
    """
    Streaming custom function that yields events during execution and returns TaskOutput
    """
    query = task_input.get_primary_input()

    # Add custom context and formatting
    enhanced_query = f"""
        BLOG ANALYSIS REQUEST:
        Topic: {query}

        Please provide:
        1. Key themes and trends
        2. Target audience insights
        3. Content opportunities
        4. SEO considerations

        Additional context from previous tasks:
        {task_input.previous_outputs if task_input.previous_outputs else "No previous context"}
    """

    # Call the agent with enhanced input
    try:
        accumulated_content = ""

        # Stream the agent response
        response_stream = await blog_analyzer.arun(enhanced_query, stream=True, stream_intermediate_steps=True)
        async for event in response_stream:
            yield event
            if hasattr(event, "content") and event.content:
                accumulated_content += event.content

        # Custom postprocessing
        enhanced_content = f"""
## Custom Blog Analysis Results

**Original Query:** {query}

**Analysis:**
{accumulated_content}

**Custom Insights:**
- Analysis completed with enhanced context
- Ready for next stage processing
- Confidence level: High
        """.strip()

        # Yield final TaskOutput
        yield TaskOutput(
            content=enhanced_content,
            data={"analysis_type": "custom", "confidence": "high"},
            metadata={
                "function_name": "streaming_blog_analysis_function",
                "preprocessing": True,
                "postprocessing": True,
                "streaming": True,
            },
        )

    except Exception as e:
        yield TaskErrorEvent(
            task_name="streaming_analysis",
            error=f"Custom blog analysis failed: {str(e)}",
        )


async def streaming_team_research_function(
    task_input: TaskInput,
) -> AsyncIterator[Union[WorkflowRunResponseEvent, TaskOutput]]:
    """
    Streaming custom function that coordinates team execution with streaming updates
    """
    query = task_input.get_primary_input()

    # Get the output from the previous task
    previous_analysis = ""
    if task_input.previous_outputs:
        previous_analysis = (
            task_input.previous_outputs.get("custom_analysis", "")
            or task_input.previous_outputs.get("output", "")
            or task_input.previous_outputs.get("result", "")
        )

    # Create enhanced team prompt
    team_prompt = f"""
        RESEARCH COORDINATION REQUEST:

        Primary Topic: {query}

        Previous Analysis: {previous_analysis[:500] if previous_analysis else "No previous analysis"}

        Team Mission:
        1. Build upon the previous analysis
        2. Conduct deeper research on the topic
        3. Validate and expand findings
        4. Provide actionable recommendations

        Please coordinate effectively and provide a unified research report.
    """

    try:
        accumulated_content = ""

        # Stream the team response
        response_stream = await research_team.arun(team_prompt, stream=True, stream_intermediate_steps=True)
        async for event in response_stream:
            yield event
            if hasattr(event, "content") and event.content:
                accumulated_content += event.content

        enhanced_content = f"""
## Custom Team Research Report

**Research Topic:** {query}

**Previous Analysis Integration:** {"✓ Integrated" if previous_analysis else "✗ No previous context"}

**Team Coordination Results:**
{accumulated_content}

**Custom Team Insights:**
- Multi-agent coordination completed
- Cross-validated findings included
- Ready for strategic planning phase
        """.strip()

        yield TaskOutput(
            content=enhanced_content,
            data={
                "research_type": "team_coordination",
                "integration": bool(previous_analysis),
            },
            metadata={
                "function_name": "streaming_team_research_function",
                "team_coordination": True,
                "previous_context": bool(previous_analysis),
                "streaming": True,
            },
        )

    except Exception as e:
        yield TaskErrorEvent(
            task_name="streaming_research",
            error=f"Custom team research failed: {str(e)}",
        )


async def streaming_content_planning_function(
    task_input: TaskInput,
) -> AsyncIterator[Union[WorkflowRunResponseEvent, TaskOutput]]:
    """
    Streaming custom function for intelligent content planning with real-time updates
    """
    query = task_input.get_primary_input()

    # Get the output from the previous task
    previous_research = ""
    if task_input.previous_outputs:
        previous_research = (
            task_input.previous_outputs.get("custom_research", "")
            or task_input.previous_outputs.get("output", "")
            or task_input.previous_outputs.get("result", "")
        )

    # Create intelligent planning prompt
    planning_prompt = f"""
        STRATEGIC CONTENT PLANNING REQUEST:

        Core Topic: {query}

        Research Foundation: {previous_research[:500] if previous_research else "No research foundation"}

        Planning Requirements:
        1. Create a comprehensive content strategy based on the research
        2. Leverage the research findings effectively
        3. Identify content formats and channels
        4. Provide timeline and priority recommendations
        5. Include engagement and distribution strategies

        Please create a detailed, actionable content plan.
    """

    try:
        accumulated_content = ""

        # Stream the content planner response
        response_stream = await content_planner.arun(planning_prompt, stream=True, stream_intermediate_steps=True)
        async for event in response_stream:
            yield event
            if hasattr(event, "content") and event.content:
                accumulated_content += event.content

        enhanced_content = f"""
## Strategic Content Plan

**Planning Topic:** {query}

**Research Integration:** {"✓ Research-based" if previous_research else "✗ No research foundation"}

**Content Strategy:**
{accumulated_content}

**Custom Planning Enhancements:**
- Research Integration: {"High" if previous_research else "Baseline"}
- Strategic Alignment: Optimized for multi-channel distribution
- Execution Ready: Detailed action items included
        """.strip()

        yield TaskOutput(
            content=enhanced_content,
            data={
                "planning_type": "strategic",
                "research_integration": bool(previous_research),
            },
            metadata={
                "function_name": "streaming_content_planning_function",
                "strategic_planning": True,
                "research_based": bool(previous_research),
                "streaming": True,
            },
        )

    except Exception as e:
        yield TaskErrorEvent(
            task_name="streaming_planning",
            error=f"Custom content planning failed: {str(e)}",
        )


# Define tasks using different executor types
custom_analysis_task = Task(
    name="custom_analysis",
    execution_function=streaming_blog_analysis_function,  # Custom function with agent
    description="Custom blog analysis with preprocessing and postprocessing",
)

custom_research_task = Task(
    name="custom_research",
    execution_function=streaming_team_research_function,  # Custom function with team
    description="Custom team research with coordination logic",
)

custom_planning_task = Task(
    name="custom_planning",
    execution_function=streaming_content_planning_function,  # Custom function with agent
    description="Custom content planning with context integration",
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
        tasks=[custom_analysis_task, custom_research_task, custom_planning_task],
    )
    print("=== Custom Sequence (Custom Execution Functions) ===")
    try:
        await content_creation_workflow.aprint_response(
            query="AI trends in 2024", markdown=True, stream=True, stream_intermediate_steps=True
        )
    except Exception as e:
        print(f"Custom sequence failed: {e}")

    print("\n" + "=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
