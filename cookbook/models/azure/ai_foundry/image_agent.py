from agno.agent import Agent
from agno.media import Image
from agno.models.azure.ai_foundry import AzureAIFoundry

agent = Agent(
    model=AzureAIFoundry(id="Llama-3.2-11B-Vision-Instruct"),
    markdown=True,
)

agent.print_response(
    "Tell me about this image.",
    images=[
        Image(
            url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg",
            detail="High"
        )
    ],
    stream=True,
)
