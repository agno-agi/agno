from agno.agent import Agent
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    reasoning=True,
    stream_intermediate_steps=True,
    debug_mode=True,
)
agent.print_response(
    "Solve the trolley problem. Evaluate multiple ethical frameworks. "
    "Include an ASCII diagram of your solution.",
    stream=True,
)

# response = agent.run(
#     "Solve the trolley problem. Evaluate multiple ethical frameworks. "
#     "Include an ASCII diagram of your solution.",
#     stream=True,
# )
# for chunk in response:
#     if chunk.event != "RunResponse":
#         print(chunk.event)
#         print(chunk.content)
#         print(" ")
