from typing import Optional

from agno.agent import Agent
from agno.eval.reliability import ExpectedToolCall, ReliabilityEval, ReliabilityResult
from agno.models.openai import OpenAIChat
from agno.run.team import TeamRunResponse
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
    ExpectedToolCall(
        tool_name="transfer_task_to_member",
        tool_call_args={"member_id": "stock-searcher"},
    ),
    ExpectedToolCall(
        tool_name="get_current_stock_price",
        tool_call_args={"symbol": "NVDA"},
    ),
]


def evaluate_team_reliability():
    response: TeamRunResponse = team.run("What is the current stock price of NVDA?")
    evaluation = ReliabilityEval(
        team_response=response,
        expected_tool_calls=expected_tool_calls,
        strict_args_check=False,  # Check if the arguments provided in the ExpectedToolCall are used
    )
    result: Optional[ReliabilityResult] = evaluation.run(print_results=True)
    result.assert_passed()


if __name__ == "__main__":
    evaluate_team_reliability()
