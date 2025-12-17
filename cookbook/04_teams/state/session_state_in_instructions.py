from agno.team.team import Team

team = Team(
    members=[],
    # Initialize the session state with a variable
    session_state={"user_name": "John"},
    instructions="Users name is {user_name}",
    markdown=True,
)

team.print_response("What is my name?", stream=True)
