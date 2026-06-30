"""
Task Dependencies Example

Demonstrates complex task dependency chains in task mode. The team leader
creates tasks where later tasks depend on earlier ones, ensuring proper
execution order. Shows how the system handles blocked tasks.

Run: .venvs/demo/bin/python cookbook/03_teams/02_modes/tasks/08_dependency_chain.py
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team.mode import TeamMode
from agno.team.team import Team

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------

market_researcher = Agent(
    name="Market Researcher",
    role="Conducts market research and competitive analysis",
    model=OpenAIResponses(id="gpt-5-mini"),
    instructions=[
        "You are a market researcher.",
        "Analyze target markets, customer segments, and competitive landscape.",
        "Provide data-driven insights and recommendations.",
    ],
)

product_strategist = Agent(
    name="Product Strategist",
    role="Develops product positioning and go-to-market strategy",
    model=OpenAIResponses(id="gpt-5-mini"),
    instructions=[
        "You are a product strategist.",
        "Based on market research, develop product positioning and strategy.",
        "Define value propositions, target segments, and differentiation.",
    ],
)

content_creator = Agent(
    name="Content Creator",
    role="Creates marketing content and messaging",
    model=OpenAIResponses(id="gpt-5-mini"),
    instructions=[
        "You are a content creator.",
        "Create compelling marketing copy based on the product strategy.",
        "Write headlines, taglines, and key messages.",
    ],
)

launch_coordinator = Agent(
    name="Launch Coordinator",
    role="Creates launch timelines and action plans",
    model=OpenAIResponses(id="gpt-5-mini"),
    instructions=[
        "You are a launch coordinator.",
        "Create detailed launch timelines with milestones.",
        "Coordinate all launch activities into a cohesive plan.",
    ],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------

launch_team = Team(
    name="Product Launch Team",
    mode=TeamMode.tasks,
    model=OpenAIResponses(id="gpt-5.2"),
    members=[
        market_researcher,
        product_strategist,
        content_creator,
        launch_coordinator,
    ],
    instructions=[
        "You are a product launch team leader.",
        "Create tasks with proper dependencies to form a pipeline:",
        "1. First: Market Researcher conducts research (no dependencies)",
        "2. Then: Product Strategist develops strategy (depends on research)",
        "3. Then: Content Creator writes messaging (depends on strategy)",
        "4. Finally: Launch Coordinator creates the launch plan (depends on all above)",
        "Use depends_on to enforce this ordering.",
        "Execute the first task, then as each completes, execute the next in the chain.",
    ],
    show_members_responses=True,
    markdown=True,
    max_iterations=15,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    launch_team.print_response(
        "Plan a product launch for a new AI-powered code review tool "
        "targeting mid-size software companies. The tool uses LLMs to "
        "provide automated code reviews with natural language explanations."
    )
