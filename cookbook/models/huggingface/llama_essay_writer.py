import os
from getpass import getpass

from agno.agent import Agent
from agno.models.huggingface import HuggingFace

agent = Agent(
    model=HuggingFace(
        id="meta-llama/Meta-Llama-3-8B-Instruct",
        max_tokens=4096,
    ),
    description="You are an essay writer. Write a 300 words essay on topic that will be provided by user",
)
agent.print_response("topic: AI")
