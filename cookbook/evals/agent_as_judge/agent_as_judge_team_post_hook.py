"""AgentAsJudgeEval as post-hook on Team."""

from agno.agent import Agent
from agno.eval.agent_as_judge import AgentAsJudgeEval
from agno.models.openai import OpenAIChat
from agno.team.team import Team

# Setup AgentAsJudgeEval as post-hook
agent_as_judge_eval = AgentAsJudgeEval(
    name="Team Response Quality",
    model=OpenAIChat(id="gpt-4o-mini"),
    criteria="Response should be well-researched, clear, comprehensive, and show good collaboration between team members",
    threshold=7,
    print_results=True,
    print_summary=True,
)

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
    post_hooks=[agent_as_judge_eval],
)

response = research_team.run("Explain quantum computing")
print(response.content)
