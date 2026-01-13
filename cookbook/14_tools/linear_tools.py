from agno.agent import Agent
from agno.tools.linear import LinearTools

agent = Agent(
    name="Linear Tool Agent",
    tools=[LinearTools()],
    markdown=True,
)


user_id = "69069"
issue_id = "6969"
team_id = "73"
new_title = "updated title for issue"
new_issue_title = "title for new issue"
desc = "issue description"

agent.print_response("Get all the details of current user")
agent.print_response(f"Show the issue with the issue id: {issue_id}")
agent.print_response(
    f"Create a new issue with the title: {new_issue_title} with description: {desc} and team id: {team_id}"
)
agent.print_response(
    f"Update the issue with the issue id: {issue_id} with new title: {new_title}"
)
agent.print_response(f"Show all the issues assigned to user id: {user_id}")
agent.print_response("Show all the high priority issues")
