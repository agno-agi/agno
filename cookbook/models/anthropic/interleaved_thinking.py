from agno.agent import Agent, RunResponse
from agno.models.anthropic import Claude

# Create agent with interleaved thinking enabled
agent = Agent(
    model=Claude(
        id="claude-sonnet-4-20250514",
        thinking={"type": "enabled", "budget_tokens": 2048},
        default_headers={"anthropic-beta": "interleaved-thinking-2025-05-14"},
    ),
    markdown=True,
)

# Get the response with thinking content
run: RunResponse = agent.run("What's 25 × 17? Think through it step by step.")

print("🤖 Response:")
print(run.content)

print("\n🧠 Thinking Process:")
if run.thinking:
    print(run.thinking)
else:
    print("No thinking content available")

# Print the response in the terminal (alternative approach)
# agent.print_response("What's 25 × 17? Think through it step by step.")
