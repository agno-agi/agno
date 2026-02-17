"""
Step With Additional Data
=========================

Demonstrates custom step executors that consume `additional_data` in sync and async workflow runs.
"""

import asyncio
from typing import AsyncIterator, Union

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.run.workflow import WorkflowRunOutputEvent
from agno.team import Team
from agno.tools.hackernews import HackerNewsTools
from agno.tools.websearch import WebSearchTools
from agno.workflow.step import Step, StepInput, StepOutput
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
hackernews_agent = Agent(
    name="Hackernews Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[HackerNewsTools()],
    instructions="Extract key insights and content from Hackernews posts",
)

web_agent = Agent(
    name="Web Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[WebSearchTools()],
    instructions="Search the web for the latest news and trends",
)

content_planner = Agent(
    name="Content Planner",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "Plan a content schedule over 4 weeks for the provided topic and research content",
        "Ensure that I have posts for 3 posts per week",
    ],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
research_team = Team(
    name="Research Team",
    members=[hackernews_agent, web_agent],
    instructions="Analyze content and create comprehensive social media strategy",
)


# ---------------------------------------------------------------------------
# Define Function Executors
# ---------------------------------------------------------------------------
def custom_content_planning_function(step_input: StepInput) -> StepOutput:
    message = step_input.input
    previous_step_content = step_input.previous_step_content

    additional_data = step_input.additional_data or {}
    user_email = additional_data.get("user_email", "No email provided")
    priority = additional_data.get("priority", "normal")
    client_type = additional_data.get("client_type", "standard")

    planning_prompt = f"""
        STRATEGIC CONTENT PLANNING REQUEST:

        Core Topic: {message}

        Research Results: {previous_step_content[:500] if previous_step_content else "No research results"}

        Additional Context:
        - Client Type: {client_type}
        - Priority Level: {priority}
        - Contact Email: {user_email}

        Planning Requirements:
        1. Create a comprehensive content strategy based on the research
        2. Leverage the research findings effectively
        3. Identify content formats and channels
        4. Provide timeline and priority recommendations
        5. Include engagement and distribution strategies
        {"6. Mark as HIGH PRIORITY delivery" if priority == "high" else "6. Standard delivery timeline"}

        Please create a detailed, actionable content plan.
    """

    try:
        response = content_planner.run(planning_prompt)
        enhanced_content = f"""
            ## Strategic Content Plan

            **Planning Topic:** {message}

            **Client Details:**
            - Type: {client_type}
            - Priority: {priority.upper()}
            - Contact: {user_email}

            **Research Integration:** {"✓ Research-based" if previous_step_content else "✗ No research foundation"}

            **Content Strategy:**
            {response.content}

            **Custom Planning Enhancements:**
            - Research Integration: {"High" if previous_step_content else "Baseline"}
            - Strategic Alignment: Optimized for multi-channel distribution
            - Execution Ready: Detailed action items included
            - Priority Level: {priority.upper()}
        """.strip()
        return StepOutput(content=enhanced_content)
    except Exception as e:
        return StepOutput(
            content=f"Custom content planning failed: {str(e)}",
            success=False,
        )


async def custom_content_planning_function_async(
    step_input: StepInput,
) -> AsyncIterator[Union[WorkflowRunOutputEvent, StepOutput]]:
    message = step_input.input
    previous_step_content = step_input.previous_step_content

    additional_data = step_input.additional_data or {}
    user_email = additional_data.get("user_email", "No email provided")
    priority = additional_data.get("priority", "normal")
    client_type = additional_data.get("client_type", "standard")

    planning_prompt = f"""
        STRATEGIC CONTENT PLANNING REQUEST:

        Core Topic: {message}

        Research Results: {previous_step_content[:500] if previous_step_content else "No research results"}

        Additional Context:
        - Client Type: {client_type}
        - Priority Level: {priority}
        - Contact Email: {user_email}

        Planning Requirements:
        1. Create a comprehensive content strategy based on the research
        2. Leverage the research findings effectively
        3. Identify content formats and channels
        4. Provide timeline and priority recommendations
        5. Include engagement and distribution strategies
        {"6. Mark as HIGH PRIORITY delivery" if priority == "high" else "6. Standard delivery timeline"}

        Please create a detailed, actionable content plan.
    """

    try:
        response_iterator = content_planner.arun(
            planning_prompt,
            stream=True,
            stream_events=True,
        )
        async for event in response_iterator:
            yield event

        response = content_planner.get_last_run_output()
        enhanced_content = f"""
            ## Strategic Content Plan

            **Planning Topic:** {message}

            **Client Details:**
            - Type: {client_type}
            - Priority: {priority.upper()}
            - Contact: {user_email}

            **Research Integration:** {"✓ Research-based" if previous_step_content else "✗ No research foundation"}

            **Content Strategy:**
            {response.content}

            **Custom Planning Enhancements:**
            - Research Integration: {"High" if previous_step_content else "Baseline"}
            - Strategic Alignment: Optimized for multi-channel distribution
            - Execution Ready: Detailed action items included
            - Priority Level: {priority.upper()}
        """.strip()
        yield StepOutput(content=enhanced_content)
    except Exception as e:
        yield StepOutput(
            content=f"Custom content planning failed: {str(e)}",
            success=False,
        )


# ---------------------------------------------------------------------------
# Define Steps
# ---------------------------------------------------------------------------
research_step = Step(
    name="Research Step",
    team=research_team,
)

content_planning_step = Step(
    name="Content Planning Step",
    executor=custom_content_planning_function,
)

content_planning_step_async = Step(
    name="Content Planning Step",
    executor=custom_content_planning_function_async,
)

# ---------------------------------------------------------------------------
# Create Workflows
# ---------------------------------------------------------------------------
content_creation_workflow = Workflow(
    name="Content Creation Workflow",
    description="Automated content creation with custom execution options",
    db=SqliteDb(
        session_table="workflow_session",
        db_file="tmp/workflow.db",
    ),
    steps=[research_step, content_planning_step],
)

async_content_creation_workflow = Workflow(
    name="Content Creation Workflow",
    description="Automated content creation with custom execution options",
    db=SqliteDb(
        session_table="workflow_session",
        db_file="tmp/workflow.db",
    ),
    steps=[research_step, content_planning_step_async],
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Sync
    content_creation_workflow.print_response(
        input="AI trends in 2024",
        additional_data={
            "user_email": "kaustubh@agno.com",
            "priority": "high",
            "client_type": "enterprise",
        },
        markdown=True,
        stream=True,
    )

    print("\n" + "=" * 60 + "\n")

    # Async
    asyncio.run(
        async_content_creation_workflow.aprint_response(
            input="AI trends in 2024",
            additional_data={
                "user_email": "kaustubh@agno.com",
                "priority": "high",
                "client_type": "enterprise",
            },
            markdown=True,
            stream=True,
        )
    )
