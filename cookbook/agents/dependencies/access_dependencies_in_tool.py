"""
Example showing how tools can access dependencies passed to the agent.

This demonstrates:
1. Passing dependencies to agent.run()
2. A simple tool function that can access and use those dependencies
3. Proper instructions to guide the agent to use the tool
"""

from datetime import datetime
from typing import Any, Dict, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIChat


def get_user_profile(user_id: str = "john_doe") -> dict:
    """Get user profile information."""
    profiles = {
        "john_doe": {
            "name": "John Doe",
            "preferences": ["AI/ML", "Software Engineering", "Finance"],
            "location": "San Francisco, CA",
            "role": "Senior Software Engineer",
        },
        "jane_smith": {
            "name": "Jane Smith",
            "preferences": ["Data Science", "Machine Learning", "Python"],
            "location": "New York, NY",
            "role": "Data Scientist",
        },
    }
    return profiles.get(user_id, {"name": "Unknown User"})


def get_current_context() -> dict:
    """Get current contextual information like time, weather, etc."""
    return {
        "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": "PST",
        "day_of_week": datetime.now().strftime("%A"),
    }


def analyze_user_with_dependencies(
    user_id: str, dependencies: Optional[Dict[str, Any]] = None
) -> str:
    """
    Analyze user using available dependencies passed to the agent.

    Use this tool when you need to analyze a specific user's profile and context.

    Args:
        user_id: The user ID to analyze
        dependencies: Dependencies passed to the agent (automatically injected)

    Returns:
        Analysis results using the available dependencies
    """
    if not dependencies:
        return "No dependencies available for analysis."

    print(f"--> Tool received dependencies: {list(dependencies.keys())}")

    results = [f"=== USER ANALYSIS FOR {user_id.upper()} ==="]

    # Use user_profile dependency if available
    if "user_profile" in dependencies:
        profile_func = dependencies["user_profile"]
        if callable(profile_func):
            profile = profile_func(user_id)
            results.append(f"Profile Data: {profile}")
        else:
            results.append(f"Profile Data (static): {profile_func}")

    # Use current_context dependency if available
    if "current_context" in dependencies:
        context_func = dependencies["current_context"]
        if callable(context_func):
            context = context_func()
            results.append(f"Current Context: {context}")
        else:
            results.append(f"Current Context (static): {context_func}")

    # Add analysis insights
    results.append(
        "ANALYSIS: This user appears to be active and engaged based on available data."
    )

    print(f"--> Tool returned results: {results}")

    return "\n\n".join(results)


def main():
    # Create an agent with the analysis tool function
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[analyze_user_with_dependencies],
        name="User Analysis Agent",
        description="An agent that can analyze users using dependency injection.",
        instructions=[
            "You are a user analysis expert.",
            "When asked to analyze a user, always use the analyze_user_with_dependencies tool.",
            "This tool has access to user profiles and current context through dependencies.",
            "Provide insights based on the tool results.",
        ],
    )

    print("=== Tool Dependencies Access Example ===\n")

    # Example: Tool accessing dependencies
    response = agent.run(
        input="Please analyze user 'john_doe' using the available data sources and provide insights about their background and preferences.",
        dependencies={
            "user_profile": get_user_profile,
            "current_context": get_current_context,
        },
        session_id="test_tool_dependencies",
    )

    print(f"Agent Response: {response.content}")


if __name__ == "__main__":
    main()
