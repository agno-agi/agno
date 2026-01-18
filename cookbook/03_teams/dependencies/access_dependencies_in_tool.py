"""
Example showing how team tools can access dependencies passed to the team.

This demonstrates:
1. Passing dependencies to team.run()
2. A team tool that receives resolved dependencies
3. Team members working together with shared data sources
"""

from datetime import datetime
from typing import Any, Dict, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team import Team


def get_current_context() -> dict:
    """Get current contextual information like time, weather, etc."""
    return {
        "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": "PST",
        "day_of_week": datetime.now().strftime("%A"),
    }


def analyze_team_performance(
    team_id: str, dependencies: Optional[Dict[str, Any]] = None
) -> str:
    """
    Analyze team performance using available data sources.

    This tool analyzes team metrics and provides insights.
    Call this tool with the team_id you want to analyze.

    Args:
        team_id: The team ID to analyze (e.g., 'engineering_team', 'sales_team')
        dependencies: Available data sources (automatically provided)

    Returns:
        Detailed team performance analysis and insights
    """
    if not dependencies:
        return "No data sources available for analysis."

    print(f"--> Team tool received data sources: {list(dependencies.keys())}")

    results = [f"=== TEAM PERFORMANCE ANALYSIS FOR {team_id.upper()} ==="]

    # Use team metrics data if available
    if "team_metrics" in dependencies:
        metrics_data = dependencies["team_metrics"]
        results.append(f"Team Metrics: {metrics_data}")

        # Add analysis based on the metrics
        if metrics_data.get("productivity_score"):
            score = metrics_data["productivity_score"]
            if score >= 8:
                results.append(
                    f"Performance Analysis: Excellent performance with {score}/10 productivity score"
                )
            elif score >= 6:
                results.append(
                    f"Performance Analysis: Good performance with {score}/10 productivity score"
                )
            else:
                results.append(
                    f"Performance Analysis: Needs improvement with {score}/10 productivity score"
                )

    # Use current context data if available
    if "current_context" in dependencies:
        context_data = dependencies["current_context"]
        results.append(f"Current Context: {context_data}")
        results.append(
            f"Time-based Analysis: Team analysis performed on {context_data['day_of_week']} at {context_data['current_time']}"
        )

    print(f"--> Team tool returned results: {results}")

    return "\n\n".join(results)


# Create team members
data_analyst = Agent(
    model=OpenAIChat(id="gpt-4o"),
    name="Data Analyst",
    description="Specialist in analyzing team metrics and performance data",
    instructions=[
        "You are a data analysis expert focusing on team performance metrics.",
        "Interpret quantitative data and identify trends.",
        "Provide data-driven insights and recommendations.",
    ],
)

team_lead = Agent(
    model=OpenAIChat(id="gpt-4o"),
    name="Team Lead",
    description="Experienced team leader who provides strategic insights",
    instructions=[
        "You are an experienced team leader and management expert.",
        "Focus on leadership insights and team dynamics.",
        "Provide strategic recommendations for team improvement.",
        "Collaborate with the data analyst to get comprehensive insights.",
    ],
)

# Create a team with the analysis tool
performance_team = Team(
    model=OpenAIChat(id="gpt-4o"),
    members=[data_analyst, team_lead],
    tools=[analyze_team_performance],
    name="Team Performance Analysis Team",
    description="A team specialized in analyzing team performance using integrated data sources.",
    instructions=[
        "You are a team performance analysis unit with access to team metrics and analysis tools.",
        "When asked to analyze any team, use the analyze_team_performance tool first.",
        "This tool has access to team metrics and current context through integrated data sources.",
        "Data Analyst: Focus on the quantitative metrics and trends.",
        "Team Lead: Provide strategic insights and management recommendations.",
        "Work together to provide comprehensive team performance insights.",
    ],
)

print("=== Team Tool Dependencies Access Example ===\n")

response = performance_team.run(
    input="Please analyze the 'engineering_team' performance and provide comprehensive insights about their productivity and recommendations for improvement.",
    dependencies={
        "team_metrics": {
            "team_name": "Engineering Team Alpha",
            "team_size": 8,
            "productivity_score": 7.5,
            "sprint_velocity": 85,
            "bug_resolution_rate": 92,
            "code_review_turnaround": "2.3 days",
            "areas": ["Backend Development", "Frontend Development", "DevOps"],
        },
        "current_context": get_current_context,
    },
    session_id="test_team_tool_dependencies",
)

print(f"\nTeam Response: {response.content}")
