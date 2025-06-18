"""
Independent Tasks Examples

This file demonstrates an approaches to using independent tasks in workflows:

Completely Independent Tasks
   - Tasks run completely independently with no data sharing
   - Each task operates on different domains/topics
   - Perfect for parallel workflows where tasks don't need to coordinate
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.workflow.v2 import Task, Workflow

# =============================================================================
# EXAMPLE: Completely Independent Tasks
# =============================================================================

# Create specialized agents for completely independent operations
tech_researcher = Agent(
    name="Tech Researcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[HackerNewsTools()],
    instructions=[
        "You are a technology research specialist.",
        "Research and summarize the latest tech trends and news.",
        "Focus on AI, software development, and emerging technologies.",
        "Provide concise, insightful summaries.",
    ],
)

market_analyst = Agent(
    name="Market Analyst",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    instructions=[
        "You are a market analysis specialist.",
        "Research market trends and business news.",
        "Focus on stock markets, economic indicators, and business developments.",
        "Provide clear, actionable insights.",
    ],
)

weather_reporter = Agent(
    name="Weather Reporter",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    instructions=[
        "You are a weather reporting specialist.",
        "Provide current weather conditions and forecasts.",
        "Focus on clear, practical weather information.",
        "Include recommendations based on conditions.",
    ],
)


def example_independent():
    """Example 2: Completely independent tasks with no shared state"""
    print("\n" + "=" * 70)
    print("🚀 EXAMPLE 2: Completely Independent Tasks")
    print("=" * 70)
    print("🔄 Each task runs independently on different topics with no data sharing")
    print()

    # Create completely independent tasks
    tasks = [
        Task(
            name="Tech News Research",
            agent=tech_researcher,
            message="Research the top 3 technology trends from Hacker News today. Focus on AI and software development.",
            independent=True,
        ),
        Task(
            name="Market Analysis",
            agent=market_analyst,
            message="Research current stock market trends and provide a brief analysis of today's market movements.",
            independent=True,
        ),
        Task(
            name="Weather Report",
            agent=weather_reporter,
            message="Get the current weather forecast for San Francisco and provide clothing recommendations.",
            independent=True,
        ),
    ]

    # Create workflow with no shared state
    independent_workflow = Workflow(
        name="Daily Information Briefing",
        description="Get independent updates on tech, markets, and weather",
        tasks=tasks,
        debug_mode=True,
    )

    # Run the workflow
    independent_workflow.print_response()


if __name__ == "__main__":
    example_independent()
