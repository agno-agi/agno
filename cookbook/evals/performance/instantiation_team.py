"""Run `pip install agno openai` to install dependencies."""

from agno.agent import Agent
from agno.eval.performance import PerformanceEval
from agno.models.openai import OpenAIChat
from agno.team.team import Team

team_member = Agent(model=OpenAIChat(id="gpt-4o"))


def instantiate_team():
    return Team(members=[team_member])


instantiation_perf = PerformanceEval(
    name="Instantiation Performance Team", func=instantiate_team, num_iterations=1000
)

if __name__ == "__main__":
    instantiation_perf.run(print_results=True, print_summary=True)
