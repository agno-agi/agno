from typing import Optional

from agno.agent import Agent
from agno.eval.reliability import ReliabilityEval, ReliabilityResult
from agno.models.openai import OpenAIChat
from agno.run.team import TeamRunOutput
from agno.team.team import Team
from agno.tools.yfinance import YFinanceTools

team_member = Agent(
    name="Stock Searcher",
    model=OpenAIChat("gpt-4o"),
    role="Searches the web for information on a stock.",
    tools=[YFinanceTools(stock_price=True)],
)

team = Team(
    name="Stock Research Team",
    model=OpenAIChat("gpt-4o"),
    members=[team_member],
    markdown=True,
    show_members_responses=True,
)

expected_tool_calls = [
    "delegate_task_to_member",  # Tool call used to delegate a task to a Team member
    "get_current_stock_price",  # Tool call used to get the current stock price of a stock
]


def evaluate_team_reliability():
    response: TeamRunOutput = team.run("What is the current stock price of NVDA?")
    evaluation = ReliabilityEval(
        name="Team Reliability Evaluation",
        team_response=response,
        expected_tool_calls=expected_tool_calls,
    )
    result: Optional[ReliabilityResult] = evaluation.run(print_results=True)
    if result:
        result.assert_passed()


if __name__ == "__main__":
    evaluate_team_reliability()
