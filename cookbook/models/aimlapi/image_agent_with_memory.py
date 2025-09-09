from agno.agent import Agent
from agno.media import Image
from agno.models.aimlapi import AIMLAPI

agent = Agent(
    model=AIMLAPI(id="meta-llama/Llama-3.2-11B-Vision-Instruct-Turbo"),
    markdown=True,
    add_history_to_context=True,
    num_history_runs=3,
)

agent.print_response(
    "Tell me about this image",
    images=[
        Image(
            url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg"
        )
    ],
    stream=True,
)

agent.print_response("Tell me where I can get more images?")
