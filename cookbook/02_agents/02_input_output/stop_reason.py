"""
Demonstrates how to check stop_reason to understand why the model stopped generating.

stop_reason tells you WHY the model stopped:
- "end_turn": Normal completion
- "max_tokens": Hit the output token limit (response may be truncated)
- "tool_use": Model wants to call a tool
- "stop_sequence": Hit a custom stop sequence
- "refusal": Model refused to respond
"""

from agno.agent import Agent
from agno.models.anthropic import Claude

# Example 1: Normal completion
agent = Agent(
    model=Claude(id="claude-sonnet-4-20250514", max_tokens=100),
    markdown=True,
)

response = agent.run("Say hello in one sentence.")
print("Example 1: Normal completion")
print(f"Content: {response.content}")
print(f"Stop reason: {response.stop_reason}")
print()

# Example 2: Truncated response (max_tokens hit)
agent_truncated = Agent(
    model=Claude(id="claude-sonnet-4-20250514", max_tokens=10),
    markdown=True,
)

response_truncated = agent_truncated.run("Write a detailed essay about climate change.")
print("Example 2: Truncated response (max_tokens=10)")
print(f"Content: {response_truncated.content}")
print(f"Stop reason: {response_truncated.stop_reason}")
print()

# Example 3: Check stop_reason to handle truncation
if response_truncated.stop_reason == "max_tokens":
    print("Warning: Response was truncated due to max_tokens limit.")
    print("Consider increasing max_tokens or asking the model to continue.")
print()

# Example 4: Streaming with stop_reason
from agno.run.agent import RunOutput

print("Example 4: Streaming with truncation")
for chunk in agent_truncated.run(
    "Explain quantum computing", stream=True, yield_run_output=True
):
    if isinstance(chunk, RunOutput):
        print(f"\nFinal stop_reason: {chunk.stop_reason}")
