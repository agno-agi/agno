"""Binary scoring mode example - PASS/FAIL evaluation."""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.eval.agent_as_judge import AgentAsJudgeEval
from agno.models.openai import OpenAIChat

# Setup database to persist eval results
db = SqliteDb(db_file="tmp/agent_as_judge_binary.db")

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    instructions="You are a customer service agent. Respond professionally.",
    db=db,
)

response = agent.run("I need help with my account")

evaluation = AgentAsJudgeEval(
    name="Professional Tone Check",
    criteria="Response must maintain professional tone without informal language or slang",
    db=db,
)

result = evaluation.run(
    input="I need help with my account",
    output=str(response.content),
    print_results=True,
    print_summary=True,
)

print(f"Result: {'PASSED' if result.results[0].passed else 'FAILED'}")
