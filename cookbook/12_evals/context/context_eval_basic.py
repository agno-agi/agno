"""
ContextEval analyzes the agent's response against its system message (description, role, instructions)
and provides aspect-based feedback.
"""

from textwrap import dedent

from agno.agent import Agent
from agno.eval.context import ContextEval
from agno.models.openai import OpenAIChat

# Create an agent with specific personality and instructions
agent = Agent(
    model=OpenAIChat(id="gpt-5-mini"),
    description="You are a friendly Python tutor for beginners.",
    role="Python Programming Tutor",
    instructions=dedent("""\
        - Always explain concepts step by step
        - Use simple analogies to explain programming concepts
        - Provide code examples with comments
        - End responses with a practice exercise
        - Keep a warm, encouraging tone
    """),
)

# Run the agent
response = agent.run("What is a for loop?")
print("Agent Response:")
print(response)
print("\n" + "=" * 60 + "\n")

# Evaluate how well the response followed the system message
context_eval = ContextEval(
    name="Python Tutor Evaluation",
    model=OpenAIChat(id="gpt-5-mini"),
    threshold=7,  # Pass if score >= 7
)

result = context_eval.run(
    run_output=response,
    print_results=True,
    print_summary=True,
)

if result:
    eval_result = result.results[0]
    print(f"\nOverall Score: {eval_result.score}/10")
    print(f"Passed: {eval_result.passed}")
    print("\nAspect Scores:")
    for aspect, score in eval_result.aspect_scores.items():
        print(f"  {aspect}: {score}/10")
    print("\nAspect Feedback:")
    for aspect, feedback in eval_result.aspect_feedback.items():
        print(f"  {aspect}: {feedback}")
