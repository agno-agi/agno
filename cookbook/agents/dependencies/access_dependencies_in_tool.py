"""
Example showing how tools can access dependencies passed to the agent.

This demonstrates:
1. Passing dependencies to agent.run()
2. A simple tool that receives resolved dependencies
"""

from datetime import datetime
from typing import Any, Dict, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIChat


def get_current_context() -> dict:
    """Get current contextual information like time, weather, etc."""
    return {
        "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": "PST",
        "day_of_week": datetime.now().strftime("%A"),
    }


def analyze_user(user_id: str, dependencies: Optional[Dict[str, Any]] = None) -> str:
    """
    Analyze a specific user's profile and provide insights.

    This tool analyzes user behavior and preferences using available data sources.
    Call this tool with the user_id you want to analyze.

    Args:
        user_id: The user ID to analyze (e.g., 'john_doe', 'jane_smith')
        dependencies: Available data sources (automatically provided)

    Returns:
        Detailed analysis and insights about the user
    """
    if not dependencies:
        return "No data sources available for analysis."

    print(f"--> Tool received data sources: {list(dependencies.keys())}")

    results = [f"=== USER ANALYSIS FOR {user_id.upper()} ==="]

    # Use user profile data if available
    if "user_profile" in dependencies:
        profile_data = dependencies["user_profile"]
        results.append(f"Profile Data: {profile_data}")

        # Add analysis based on the profile
        if profile_data.get("role"):
            results.append(
                f"Professional Analysis: {profile_data['role']} with expertise in {', '.join(profile_data.get('preferences', []))}"
            )

    # Use current context data if available
    if "current_context" in dependencies:
        context_data = dependencies["current_context"]
        results.append(f"Current Context: {context_data}")
        results.append(
            f"Time-based Analysis: Analysis performed on {context_data['day_of_week']} at {context_data['current_time']}"
        )

    print(f"--> Tool returned results: {results}")

    return "\n\n".join(results)


# Create an agent with the analysis tool function
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[analyze_user],
    name="User Analysis Agent",
    description="An agent specialized in analyzing users using integrated data sources.",
    instructions=[
        "You are a user analysis expert with access to user analysis tools.",
        "When asked to analyze any user, use the analyze_user tool.",
        "This tool has access to user profiles and current context through integrated data sources.",
        "After getting tool results, provide additional insights and recommendations based on the analysis.",
        "Be thorough in your analysis and explain what the tool found.",
    ],
)

print("=== Tool Dependencies Access Example ===\n")

response = agent.run(
    input="Please analyze user 'john_doe' and provide insights about their professional background and preferences.",
    dependencies={
        "user_profile": {
            "name": "John Doe",
            "preferences": ["AI/ML", "Software Engineering", "Finance"],
            "location": "San Francisco, CA",
            "role": "Senior Software Engineer",
        },
        "current_context": get_current_context,
    },
    session_id="test_tool_dependencies",
)

print(f"\nAgent Response: {response.content}")
