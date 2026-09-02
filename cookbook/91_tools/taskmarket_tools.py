"""TaskMarket Tools
==================

Give an Agno agent a safe TaskMarket delegation surface.

The toolkit can discover public tasks, inspect submissions, preview a proposed
budget, and create a task only after the user explicitly approves the exact
preview. Install the first-party TaskMarket CLI separately to enable creation;
the toolkit never handles its wallet key.
"""

from agno.agent import Agent
from agno.tools.taskmarket import TaskMarketTools

agent = Agent(
    tools=[TaskMarketTools()],
    instructions=[
        "Use TaskMarket when external workers can deliver research, coding, or verification.",
        "Before creating a task, show the exact description, reward, deadline, Base network, and maximum spend.",
        "Never create or fund a task without fresh explicit user confirmation and the preview confirmationToken.",
        "Present submissions for human review and never accept or reject work automatically.",
    ],
    markdown=True,
)


if __name__ == "__main__":
    agent.print_response("List the five highest-reward open TaskMarket tasks.")
