from agno.agent import Agent
from agno.tools.jira import JiraTools

# Example 1: Enable all Jira functions
agent_all = Agent(
    tools=[
        JiraTools(
            all=True,  # Enable all Jira functions
        )
    ],
    markdown=True,
)

# Example 2: Enable specific Jira functions only
agent_specific = Agent(
    tools=[
        JiraTools(
            enable_search_issues=True,
            enable_get_issue=True,
            enable_create_issue=False,
        )
    ],
    markdown=True,
)

# Example 3: Default behavior with all functions enabled
agent = Agent(
    tools=[
        JiraTools(
            enable_search_issues=True,
            enable_get_issue=True,
            enable_create_issue=True,
        )
    ],
    markdown=True,
)

# Example usage with all functions enabled
print("=== Example 1: Using all Jira functions ===")
agent_all.print_response(
    "Find all issues in project PROJ and create a summary report", markdown=True
)

# Example usage with specific functions only
print("\n=== Example 2: Using specific Jira functions (read-only) ===")
agent_specific.print_response("Find all issues in project PROJ", markdown=True)

# Example usage with default configuration
print("\n=== Example 3: Default Jira agent usage ===")
agent.print_response("Find all issues in project PROJ", markdown=True)

agent.print_response("Get details for issue PROJ-123", markdown=True)
