"""AgentAsJudgeEval with teams."""

from typing import Optional

from agno.agent import Agent
from agno.eval.agent_as_judge import AgentAsJudgeEval, AgentAsJudgeResult
from agno.models.openai import OpenAIChat
from agno.team.team import Team

# Setup a team with researcher and writer
researcher = Agent(
    name="Researcher",
    role="Research and gather information",
    model=OpenAIChat(id="gpt-4o"),
)

writer = Agent(
    name="Writer",
    role="Write clear and concise summaries",
    model=OpenAIChat(id="gpt-4o"),
)

research_team = Team(
    name="Research Team",
    model=OpenAIChat("gpt-4o"),
    members=[researcher, writer],
    instructions=["First research the topic thoroughly, then write a clear summary."],
)

response = research_team.run("Explain quantum computing")

evaluation = AgentAsJudgeEval(
    name="Team Response Quality",
    model=OpenAIChat(id="gpt-4o-mini"),
    criteria="Response should be well-researched, clear, and comprehensive with good flow",
    scoring_strategy="binary",
)

result: Optional[AgentAsJudgeResult] = evaluation.run(
    input="Explain quantum computing",
    output=str(response.content),
    print_results=True,
    print_summary=True,
)
assert result is not None, "Evaluation should return a result"
