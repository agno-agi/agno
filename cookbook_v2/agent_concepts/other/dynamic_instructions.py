from agno.agent import Agent


def get_instructions(agent: Agent):
    if agent.session_state and agent.session_state.get("current_user_id"):
        return f"Make the story about {agent.session_state.get('current_user_id')}."
    return "Make the story about the user."


agent = Agent(instructions=get_instructions)
agent.print_response("Write a 2 sentence story", user_id="john.doe")
