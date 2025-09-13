from agno.agent import Agent, RunOutput  # noqa
from agno.models.requesty import Requesty

agent = Agent(
    model=Requesty(
        id="anthropic/claude-opus-4.1",
        extra_body={
            "requesty": {
                "user_id": "your_user_id",
                "trace_id": "your_session_id",
            }
        },
    ),
)

# Get the response in a variable
# run: RunOutput = agent.run("Share a 2 sentence horror story")
# print(run.content)

# Print the response in the terminal
agent.print_response("Hello world!")
