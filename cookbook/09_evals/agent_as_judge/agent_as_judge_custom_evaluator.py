"""Using a custom evaluator agent instead of the default judge."""

from agno.agent import Agent
from agno.eval.agent_as_judge import AgentAsJudgeEval
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    instructions="Explain technical concepts simply.",
)

response = agent.run("What is machine learning?")

custom_evaluator = Agent(
    model=OpenAIChat(id="gpt-4o"),
    description="Strict technical evaluator",
    instructions="You are a strict evaluator. Only give high scores to exceptionally clear and accurate explanations.",
)

evaluation = AgentAsJudgeEval(
    name="Technical Accuracy",
    criteria="Explanation must be technically accurate and comprehensive",
    scoring_strategy="numeric",
    threshold=8,
    evaluator_agent=custom_evaluator,
)

result = evaluation.run(
    input="What is machine learning?",
    output=str(response.content),
    print_results=True,
)

print(f"Score: {result.results[0].score}/10")
print(f"Passed: {result.results[0].passed}")
