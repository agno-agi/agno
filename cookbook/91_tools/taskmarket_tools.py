"""TaskMarket Tools

Preview, create, and review TaskMarket requester tasks from an Agno agent.
Funded creation uses the official TaskMarket CLI and requires confirm=True.
"""

from agno.agent import Agent
from agno.tools.taskmarket import TaskMarketTools

agent = Agent(
    tools=[TaskMarketTools()],
    markdown=True,
)

if __name__ == "__main__":
    # Preview only. Creating a task spends USDC on Base and needs confirm=True
    # plus the confirm_token returned here.
    agent.print_response(
        "Preview a 2 USDC, 24 hour bounty for a short markdown summary. Show description, reward, deadline, deliverables, Base network, and max spend. Do not create it."
    )
