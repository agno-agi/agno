"""Run `pip install ddgs sqlalchemy pgvector pypdf openai groq` to install dependencies."""

from agno.agent import Agent
from agno.models.groq import Groq

agent_with_reasoning = Agent(
    model=Groq(id="Qwen-2.5-32b"),
    reasoning=True,
    reasoning_model=Groq(
        id="Deepseek-r1-distill-qwen-32b", temperature=0.6, max_tokens=1024, top_p=0.95
    ),
)
agent_with_reasoning.print_response("9.11 and 9.9 -- which is bigger?", markdown=True)
