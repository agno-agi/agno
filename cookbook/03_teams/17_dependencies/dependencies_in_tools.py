"""
Dependencies In Tools
=============================

Demonstrates passing dependencies at runtime and accessing them inside team tools.
"""

from datetime import datetime

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.run import RunContext
from agno.team import Team


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
def get_user_profile(user_id: str = "john_doe") -> dict:
    """Get user profile information that can be referenced in responses."""
    profiles = {
        "john_doe": {
            "name": "John Doe",
            "preferences": {
                "communication_style": "professional",
                "topics_of_interest": ["AI/ML", "Software Engineering", "Finance"],
                "experience_level": "senior",
            },
            "location": "San Francisco, CA",
            "role": "Senior Software Engineer",
        }
    }

    return profiles.get(user_id, {"name": "Unknown User"})


def get_current_context() -> dict:
    """Get current contextual information like time, weather, etc."""
    return {
        "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": "PST",
        "day_of_week": datetime.now().strftime("%A"),
    }


def analyze_team_performance(team_id: str, run_context: RunContext) -> str:
    """Analyze team performance using dependencies available in run context."""
    dependencies = run_context.dependencies
    if not dependencies:
        return "No data sources available for analysis."

    print(f"--> Team tool received data sources: {list(dependencies.keys())}")

    results = [f"=== TEAM PERFORMANCE ANALYSIS FOR {team_id.upper()} ==="]

    if "team_metrics" in dependencies:
        metrics_data = dependencies["team_metrics"]
        results.append(f"Team Metrics: {metrics_data}")

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

    if "current_context" in dependencies:
        context_data = dependencies["current_context"]
        results.append(f"Current Context: {context_data}")
        results.append(
            f"Time-based Analysis: Team analysis performed on {context_data['day_of_week']} at {context_data['current_time']}"
        )

    print(f"--> Team tool returned results: {results}")
    return "\n\n".join(results)


# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
data_analyst = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    name="Data Analyst",
    description="Specialist in analyzing team metrics and performance data",
    instructions=[
        "You are a data analysis expert focusing on team performance metrics.",
        "Interpret quantitative data and identify trends.",
        "Provide data-driven insights and recommendations.",
    ],
)

team_lead = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    name="Team Lead",
    description="Experienced team leader who provides strategic insights",
    instructions=[
        "You are an experienced team leader and management expert.",
        "Focus on leadership insights and team dynamics.",
        "Provide strategic recommendations for team improvement.",
        "Collaborate with the data analyst to get comprehensive insights.",
    ],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
personalization_team = Team(
    name="PersonalizationTeam",
    model=OpenAIResponses(id="gpt-5.2"),
    members=[],
    instructions=[
        "Analyze the user profile and current context to provide a personalized summary of today's priorities."
    ],
    markdown=True,
)

performance_team = Team(
    model=OpenAIResponses(id="gpt-5.2"),
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

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Team Tool Dependencies Access Example ===\n")

    personalization_response = personalization_team.run(
        "Please provide me with a personalized summary of today's priorities based on my profile and interests.",
        dependencies={
            "user_profile": get_user_profile,
            "current_context": get_current_context,
        },
        add_dependencies_to_context=True,
    )
    print(personalization_response.content)

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
