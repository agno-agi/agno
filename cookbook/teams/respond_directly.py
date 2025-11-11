# Team with respond_directly as False, with individual member agents that respond directly

from agno.agent import Agent
from agno.team.team import Team

agent1 = Agent(
    role="Agent 1",
    description="You are an agent that responds directly.",
    respond_directly=True,
)

agent2 = Agent(
    role="Agent 2",
    description="You are an agent that responds directly.",
    respond_directly=False,
)

team = Team(
    members=[agent1, agent2],
    respond_directly=False,
)

# Team with another team as a member

direct_team = Team(
    members=[agent1, agent2],
    # This will make Agent 2 respond directly, where we actually want the team to respond
    # directly in the main team
    respond_directly=True,  
)

main_team = Team(
    members=[team, agent2],
    respond_directly=False,
)