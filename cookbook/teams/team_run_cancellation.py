"""🛑 Team Run Cancellation - Stopping Collaborative Tasks

This example shows how to cancel team runs while agents are collaborating.
Useful for scenarios like:
- Long research projects with multiple agents
- Complex analysis requiring team coordination
- Multi-agent workflows that need to be stopped

Run `pip install openai agno` to install dependencies.
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team import Team

# Create a research team
researcher = Agent(
    name="Research Specialist",
    model=OpenAIChat(id="gpt-4o-mini"),
    description="Gathers comprehensive information on topics",
    instructions=["Focus on finding accurate, detailed information"]
)

analyst = Agent(
    name="Data Analyst", 
    model=OpenAIChat(id="gpt-4o-mini"),
    description="Analyzes and synthesizes research findings",
    instructions=["Look for patterns and insights in the data"]
)

writer = Agent(
    name="Report Writer",
    model=OpenAIChat(id="gpt-4o-mini"),
    description="Creates well-structured reports",
    instructions=["Write clear, comprehensive reports"]
)

# Create the team
research_team = Team(
    name="Research Analysis Team",
    members=[researcher, analyst, writer],
    description="Collaborative team for in-depth research and analysis",
    instructions=[
        "Work together to create comprehensive research reports",
        "Each member should contribute their expertise",
        "Ensure thorough analysis and clear presentation"
    ],
    markdown=True,
)

async def demonstrate_team_cancellation():
    """Show how to cancel a team collaboration mid-process"""
    
    print("🚀 Starting collaborative team research...")
    
    # Start a complex team task
    task = asyncio.create_task(
        research_team.arun(
            "Conduct a comprehensive analysis of renewable energy trends "
            "worldwide, including market data, technological advances, "
            "policy impacts, and future projections for the next decade."
        )
    )
    
    await asyncio.sleep(0.1)
    
    print("⏹️ Deciding to cancel the team collaboration...")
    cancelled = research_team.cancel_run(reason="Priorities changed")
    print(f"Team cancellation requested: {cancelled}")
    
    try:
        result = await task
        print("Team task completed:", result.content[:100] + "...")
        print("Note: Team task completed before cancellation could take effect")
        print("      (This is normal for fast-completing team tasks)")
    except Exception as e:
        from agno.exceptions import RunCancelledException
        if isinstance(e, RunCancelledException):
            print("✅ Team collaboration was successfully cancelled!")
        else:
            print(f"Unexpected error: {e}")
    
    print("\n🔬 Demonstrating team cancellation mechanism:")
    from agno.utils.events import create_team_run_response_cancelled_event
    from agno.run.team import TeamRunResponse
    
    mock_response = TeamRunResponse(run_id="test-123")
    research_team._cancellation_event = create_team_run_response_cancelled_event(
        mock_response, "Manual test of team cancellation"
    )
    
    try:
        research_team._check_for_cancellation_event()
        print("❌ Team cancellation check failed")
    except Exception as e:
        from agno.exceptions import RunCancelledException
        if isinstance(e, RunCancelledException):
            print("✅ Team cancellation mechanism working correctly!")
        else:
            print(f"Unexpected error: {e}")

if __name__ == "__main__":
    asyncio.run(demonstrate_team_cancellation())