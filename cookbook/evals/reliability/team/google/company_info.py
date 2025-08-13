from typing import Optional

from agno.agent import Agent
from agno.eval.reliability import ReliabilityEval, ReliabilityResult
from agno.models.google import Gemini
from agno.run.team import TeamRunResponse
from agno.team.team import Team
from agno.tools.yfinance import YFinanceTools

team_member = Agent(
    name="Stock Searcher",
    model=Gemini(id="gemini-2.0-flash-001"),
    role="Searches the web for information on a stock.",
    tools=[YFinanceTools(stock_price=True)],
)

team = Team(
    name="Stock Research Team",
    model=Gemini(id="gemini-2.0-flash-001"),
    members=[team_member],
    markdown=True,
    show_members_responses=True,
)

expected_tool_calls = [
    "transfer_task_to_member",  # Tool call used to transfer a task to a Team member
    "get_current_stock_price",  # Tool call used to get the current stock price of a stock
]


def evaluate_team_reliability():
    response: TeamRunResponse = team.run("What is the current stock price of NVDA?")
    evaluation = ReliabilityEval(
        name="Team Reliability Evaluation",
        team_response=response,
        expected_tool_calls=expected_tool_calls,
    )
    result: Optional[ReliabilityResult] = evaluation.run(print_results=True)
    result.assert_passed()


if __name__ == "__main__":
    evaluate_team_reliability()
