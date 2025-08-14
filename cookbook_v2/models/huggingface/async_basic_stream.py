import asyncio

from agno.agent import Agent
from agno.models.huggingface import HuggingFace

agent = Agent(
    model=HuggingFace(
        id="mistralai/Mistral-7B-Instruct-v0.2", max_tokens=4096, temperature=0
    ),
)
asyncio.run(
    agent.aprint_response(
        "What is meaning of life and then recommend 5 best books to read about it",
        stream=True,
    )
)
