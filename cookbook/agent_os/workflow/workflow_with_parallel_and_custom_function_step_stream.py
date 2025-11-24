from typing import AsyncIterator, Union

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.run.workflow import WorkflowRunOutputEvent
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.workflow.parallel import Parallel
from agno.workflow.step import Step, StepInput, StepOutput
from agno.workflow.workflow import Workflow

# Define agents for use in custom functions
hackernews_agent = Agent(
    name="Hackernews Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[HackerNewsTools()],
    instructions="Extract key insights and content from Hackernews posts",
    db=InMemoryDb(),
)

web_agent = Agent(
    name="Web Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    instructions="Search the web for the latest news and trends",
    db=InMemoryDb(),
)

content_planner = Agent(
    name="Content Planner",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "Plan a content schedule over 4 weeks for the provided topic and research content",
        "Ensure that I have posts for 3 posts per week",
    ],
    db=InMemoryDb(),
)


async def hackernews_research_function(
    step_input: StepInput,
) -> AsyncIterator[Union[WorkflowRunOutputEvent, StepOutput]]:
    """
    Custom function for HackerNews research with enhanced processing and streaming
    """
    message = step_input.input

    research_prompt = f"""
        HACKERNEWS RESEARCH REQUEST:

        Topic: {message}

        Research Tasks:
        1. Search for relevant HackerNews posts and discussions
        2. Extract key insights and trends
        3. Identify popular opinions and debates
        4. Summarize technical developments
        5. Note community sentiment and engagement levels

        Please provide comprehensive HackerNews research results.
    """

    try:
        # Stream the agent response
        response_iterator = hackernews_agent.arun(
            research_prompt, stream=True, stream_events=True
        )
        async for event in response_iterator:
            yield event

        # Get the final response
        response = hackernews_agent.get_last_run_output()

        # Check if response and content exist
        response_content = ""
        if response and hasattr(response, "content") and response.content:
            response_content = response.content
        else:
            response_content = "No content available from HackerNews research"

        enhanced_content = f"""
            ## HackerNews Research Results

            **Research Topic:** {message}
            **Source:** HackerNews Community Analysis
            **Processing:** Enhanced with custom streaming function

            **Findings:**
            {response_content}

            **Custom Function Enhancements:**
            - Community Focus: HackerNews developer perspectives
            - Technical Depth: High-level technical discussions
            - Trend Analysis: Developer sentiment and adoption patterns
            - Streaming: Real-time research progress updates
        """.strip()

        yield StepOutput(content=enhanced_content)

    except Exception as e:
        yield StepOutput(
            content=f"HackerNews research failed: {str(e)}",
            success=False,
        )


async def web_search_research_function(
    step_input: StepInput,
) -> AsyncIterator[Union[WorkflowRunOutputEvent, StepOutput]]:
    """
    Custom function for web search research with enhanced processing and streaming
    """
    message = step_input.input

    research_prompt = f"""
        WEB SEARCH RESEARCH REQUEST:

        Topic: {message}

        Research Tasks:
        1. Search for the latest news and articles
        2. Identify market trends and business implications
        3. Find expert opinions and analysis
        4. Gather statistical data and reports
        5. Note mainstream media coverage and public sentiment

        Please provide comprehensive web research results.
    """

    try:
        # Stream the agent response
        response_iterator = web_agent.arun(
            research_prompt, stream=True, stream_events=True
        )
        async for event in response_iterator:
            yield event

        # Get the final response
        response = web_agent.get_last_run_output()

        # Check if response and content exist
        response_content = ""
        if response and hasattr(response, "content") and response.content:
            response_content = response.content
        else:
            response_content = "No content available from web search research"

        enhanced_content = f"""
            ## Web Search Research Results

            **Research Topic:** {message}
            **Source:** General Web Search Analysis
            **Processing:** Enhanced with custom streaming function

            **Findings:**
            {response_content}

            **Custom Function Enhancements:**
            - Market Focus: Business and mainstream perspectives
            - Trend Analysis: Public adoption and market signals
            - Data Integration: Statistical and analytical insights
            - Streaming: Real-time research progress updates
        """.strip()

        yield StepOutput(content=enhanced_content)

    except Exception as e:
        yield StepOutput(
            content=f"Web search research failed: {str(e)}",
            success=False,
        )


async def custom_content_planning_function(
    step_input: StepInput,
) -> AsyncIterator[Union[WorkflowRunOutputEvent, StepOutput]]:
    """
    Custom function that does intelligent content planning with context awareness and streaming
    """
    message = step_input.input
    previous_step_content = step_input.previous_step_content

    # Create intelligent planning prompt
    planning_prompt = f"""
        STRATEGIC CONTENT PLANNING REQUEST:

        Core Topic: {message}

        Research Results: {previous_step_content[:1000] if previous_step_content else "No research results"}

        Planning Requirements:
        1. Create a comprehensive content strategy based on the research
        2. Leverage the research findings effectively
        3. Identify content formats and channels
        4. Provide timeline and priority recommendations
        5. Include engagement and distribution strategies

        Please create a detailed, actionable content plan.
    """

    try:
        # Stream the agent response
        response_iterator = content_planner.arun(
            planning_prompt, stream=True, stream_events=True
        )
        async for event in response_iterator:
            yield event

        # Get the final response
        response = content_planner.get_last_run_output()

        # Check if response and content exist
        response_content = ""
        if response and hasattr(response, "content") and response.content:
            response_content = response.content
        else:
            response_content = "No content available from content planning"

        enhanced_content = f"""
            ## Strategic Content Plan

            **Planning Topic:** {message}

            **Research Integration:** {"✓ Multi-source research" if previous_step_content else "✗ No research foundation"}

            **Content Strategy:**
            {response_content}

            **Custom Planning Enhancements:**
            - Research Integration: {"High (Parallel sources)" if previous_step_content else "Baseline"}
            - Strategic Alignment: Optimized for multi-channel distribution
            - Execution Ready: Detailed action items included
            - Source Diversity: HackerNews + Web + Social insights
            - Streaming: Real-time planning progress updates
        """.strip()

        yield StepOutput(content=enhanced_content)

    except Exception as e:
        yield StepOutput(
            content=f"Custom content planning failed: {str(e)}",
            success=False,
        )


# Define steps using custom streaming functions for parallel execution

hackernews_step = Step(
    name="HackerNews Research",
    executor=hackernews_research_function,
)

web_search_step = Step(
    name="Web Search Research",
    executor=web_search_research_function,
)

content_planning_step = Step(
    name="Content Planning Step",
    executor=custom_content_planning_function,
)

streaming_content_workflow = Workflow(
    name="Streaming Content Creation Workflow",
    description="Automated content creation with parallel custom streaming functions",
    db=SqliteDb(
        session_table="streaming_workflow_session",
        db_file="tmp/workflow.db",
    ),
    # Define the sequence with parallel research steps followed by planning
    steps=[
        Parallel(hackernews_step, web_search_step, name="Parallel Research Phase"),
        content_planning_step,
    ],
)

# Initialize the AgentOS with the workflows
agent_os = AgentOS(
    description="Example OS setup",
    workflows=[streaming_content_workflow],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(
        app="workflow_with_parallel_and_custom_function_step_stream:app", reload=True
    )
