from agno.agent import Agent
from agno.run import RunContext


def get_instructions(run_context: RunContext):
    if run_context.session_state and run_context.session_state.get("current_user_id"):
        return (
            f"Make the story about {run_context.session_state.get('current_user_id')}."
        )
    return "Make the story about the user."


agent = Agent(instructions=get_instructions)
agent.print_response("Write a 2 sentence story", user_id="john.doe")
