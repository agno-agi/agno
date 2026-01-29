"""Router with CEL: route based on input length.

Uses input.size() to send short queries to a quick-answer agent
and longer queries to a detailed analysis agent.

Requirements:
    pip install cel-python
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow import CEL_AVAILABLE, Step, Workflow
from agno.workflow.router import Router

if not CEL_AVAILABLE:
    print("CEL is not available. Install with: pip install cel-python")
    exit(1)

quick_agent = Agent(
    name="Quick Answer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Provide a brief, direct answer. Keep it under 2 sentences.",
    markdown=True,
)

detailed_agent = Agent(
    name="Detailed Analysis",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Provide a thorough, detailed analysis with examples and explanations.",
    markdown=True,
)

workflow = Workflow(
    name="CEL Input Length Router",
    steps=[
        Router(
            name="Length Router",
            selector='input.size() > 100 ? "Detailed Analysis" : "Quick Answer"',
            choices=[
                Step(name="Quick Answer", agent=quick_agent),
                Step(name="Detailed Analysis", agent=detailed_agent),
            ],
        ),
    ],
)

if __name__ == "__main__":
    print("--- Short input ---")
    workflow.print_response(input="What is Docker?")
    print()

    print("--- Long input ---")
    workflow.print_response(
        input=(
            "I have a complex microservices architecture with 15 services running on Kubernetes. "
            "We are experiencing intermittent latency spikes during peak hours, particularly in the "
            "payment processing pipeline. Can you help me design a comprehensive monitoring and "
            "debugging strategy?"
        ),
    )
