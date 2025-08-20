from agno.agent import Agent


def get_instructions(session_state):
    if session_state and session_state.get("current_user_id"):
        return f"Make the story about {session_state.get('current_user_id')}."
    return "Make the story about the user."


agent = Agent(instructions=get_instructions)
agent.print_response("Write a 2 sentence story", user_id="john.doe")
