from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.workflow.step import Step, StepInput, StepOutput
from agno.workflow.workflow import Workflow

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
    model=OpenAIChat(id="gpt-4o"),
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


def custom_content_planning_function(
    step_input: StepInput, session_state: dict
) -> StepOutput:
    """
    Custom function that does intelligent content planning with context awareness
    and maintains a content plan history in session_state
    """
    message = step_input.input
    previous_step_content = step_input.previous_step_content

    # Initialize content history if not present
    if "content_plans" not in session_state:
        session_state["content_plans"] = []

    if "plan_counter" not in session_state:
        session_state["plan_counter"] = 0

    # Increment plan counter
    session_state["plan_counter"] += 1
    current_plan_id = session_state["plan_counter"]

    # Create intelligent planning prompt
    planning_prompt = f"""
        STRATEGIC CONTENT PLANNING REQUEST:

        Core Topic: {message}
        Plan ID: #{current_plan_id}

        Research Results: {previous_step_content[:500] if previous_step_content else "No research results"}

        Previous Plans Count: {len(session_state["content_plans"])}

        Planning Requirements:
        1. Create a comprehensive content strategy based on the research
        2. Leverage the research findings effectively
        3. Identify content formats and channels
        4. Provide timeline and priority recommendations
        5. Include engagement and distribution strategies

        Please create a detailed, actionable content plan.
    """

    try:
        response = content_planner.run(planning_prompt)

        # Store this plan in session state
        plan_data = {
            "id": current_plan_id,
            "topic": message,
            "content": response.content,
            "timestamp": f"Plan #{current_plan_id}",
            "has_research": bool(previous_step_content),
        }
        session_state["content_plans"].append(plan_data)

        enhanced_content = f"""
            ## Strategic Content Plan #{current_plan_id}

            **Planning Topic:** {message}

            **Research Integration:** {"✓ Research-based" if previous_step_content else "✗ No research foundation"}
            **Total Plans Created:** {len(session_state["content_plans"])}

            **Content Strategy:**
            {response.content}

            **Custom Planning Enhancements:**
            - Research Integration: {"High" if previous_step_content else "Baseline"}
            - Strategic Alignment: Optimized for multi-channel distribution
            - Execution Ready: Detailed action items included
            - Session History: {len(session_state["content_plans"])} plans stored
            
            **Plan ID:** #{current_plan_id}
        """.strip()

        return StepOutput(content=enhanced_content)

    except Exception as e:
        return StepOutput(
            content=f"Custom content planning failed: {str(e)}",
            success=False,
        )


def content_summary_function(step_input: StepInput, session_state: dict) -> StepOutput:
    """
    Custom function that summarizes all content plans created in the session
    """
    if "content_plans" not in session_state or not session_state["content_plans"]:
        return StepOutput(
            content="No content plans found in session state.", success=False
        )

    plans = session_state["content_plans"]
    summary = f"""
        ## Content Planning Session Summary
        
        **Total Plans Created:** {len(plans)}
        **Session Statistics:**
        - Plans with research: {len([p for p in plans if p["has_research"]])}
        - Plans without research: {len([p for p in plans if not p["has_research"]])}
        
        **Plan Overview:**
    """

    for plan in plans:
        summary += f"""
        
        ### Plan #{plan["id"]} - {plan["topic"]}
        - Research Available: {"✓" if plan["has_research"] else "✗"}
        - Status: Completed
        """

    # Update session state with summary info
    session_state["session_summarized"] = True
    session_state["total_plans_summarized"] = len(plans)

    return StepOutput(content=summary.strip())


# Define steps using different executor types

research_step = Step(
    name="Research Step",
    team=research_team,
)

content_planning_step = Step(
    name="Content Planning Step",
    executor=custom_content_planning_function,
)

content_summary_step = Step(
    name="Content Summary Step",
    executor=content_summary_function,
)


# Define and use examples
if __name__ == "__main__":
    content_creation_workflow = Workflow(
        name="Content Creation Workflow",
        description="Automated content creation with custom execution options and session state",
        db=SqliteDb(
            session_table="workflow_session",
            db_file="tmp/workflow.db",
        ),
        # Define the sequence of steps
        # First run the research_step, then the content_planning_step, then the summary_step
        # You can mix and match agents, teams, and even regular python functions directly as steps
        steps=[research_step, content_planning_step, content_summary_step],
        # Initialize session state with empty content plans
        session_state={"content_plans": [], "plan_counter": 0},
    )

    print("=== First Workflow Run ===")
    content_creation_workflow.print_response(
        input="AI trends in 2024",
        markdown=True,
    )

    print(
        f"\nSession State After First Run: {content_creation_workflow.get_session_state()}"
    )

    print("\n" + "=" * 60 + "\n")

    print("=== Second Workflow Run (Same Session) ===")
    content_creation_workflow.print_response(
        input="Machine Learning automation tools",
        markdown=True,
    )

    print(f"\nFinal Session State: {content_creation_workflow.get_session_state()}")
