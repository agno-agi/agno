"""
Azure Image Agent
=================

Cookbook example for `azure/ai_foundry/image_agent.py`.
"""

from agno.agent import Agent
from agno.media import Image
from agno.models.azure import AzureAIFoundry

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=AzureAIFoundry(id="Llama-3.2-11B-Vision-Instruct"),
    markdown=True,
)

agent.print_response(
    "Tell me about this image.",
    images=[
        Image(
            url="https://raw.githubusercontent.com/Azure/azure-sdk-for-python/main/sdk/ai/azure-ai-inference/samples/sample1.png",
            detail="high",
        )
    ],
    stream=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
