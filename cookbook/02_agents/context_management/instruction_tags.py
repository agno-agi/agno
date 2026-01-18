"""Example demonstrating the use_instruction_tags parameter.

By default, instructions are added directly to the system message without XML tags.
Set use_instruction_tags=True to wrap instructions in <instructions> tags for
models that respond better to structured prompts.

Run: `pip install openai agno` to install the dependencies
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat

# Default behavior: instructions without tags
# The instructions are added directly to the system message
agent_without_tags = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=[
        "You are a helpful assistant.",
        "Always be concise and clear.",
        "Use bullet points when listing items.",
    ],
)

# With instruction tags enabled
# The instructions are wrapped in <instructions> tags
agent_with_tags = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=[
        "You are a helpful assistant.",
        "Always be concise and clear.",
        "Use bullet points when listing items.",
    ],
    use_instruction_tags=True,
)

print("=== Agent without instruction tags (default) ===")
agent_without_tags.print_response("What are the benefits of exercise?")

print("\n=== Agent with instruction tags ===")
agent_with_tags.print_response("What are the benefits of exercise?")
