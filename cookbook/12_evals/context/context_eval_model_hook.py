"""
ContextEval can evaluate context quality BEFORE the model generates a response.
Pass ContextEval directly to model_hooks to assess if the context is well-structured.
Use on_fail to block agent execution if context quality is poor.
"""

from agno.agent import Agent
from agno.eval.context import ContextEval, ContextEvaluation
from agno.models.openai import OpenAIChat


def stop_agent(evaluation: ContextEvaluation) -> None:
    """Stop agent execution if context evaluation fails."""
    raise ValueError(f"Context failed: {evaluation.score}/10")


# Create the context evaluator
context_eval = ContextEval(
    name="Context Quality Check",
    model=OpenAIChat(id="gpt-4o-mini"),
    threshold=9,
    print_results=True,
    print_summary=True,
    on_fail=stop_agent,
)

# Create agent with context_eval as a model hook
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    description="You are a Python expert who writes clean, documented code.",
    instructions=[
        "Always include type hints",
        "Add docstrings to functions",
        "Follow PEP 8 style guidelines",
    ],
    model_hooks=[context_eval],
)

# context will be evaluated before the model responds
response = agent.run("Write a function to check if a number is prime")
print("\nAgent Response:")
print(response.content)
