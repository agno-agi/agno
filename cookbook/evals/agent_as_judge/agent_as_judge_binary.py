"""Binary scoring mode example - PASS/FAIL evaluation."""

from agno.agent import Agent
from agno.eval.agent_as_judge import AgentAsJudgeEval
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    instructions="You are a customer service agent. Respond professionally.",
)

response = agent.run("I need help with my account")

evaluation = AgentAsJudgeEval(
    name="Professional Tone Check",
    criteria="Response must maintain professional tone without informal language or slang",
    scoring_strategy="binary",  # PASS/FAIL (no threshold needed)
)

result = evaluation.run(
    input="I need help with my account",
    output=str(response.content),
    print_results=True,
    print_summary=True,
)

print(f"Result: {'PASSED' if result.results[0].passed else 'FAILED'}")
