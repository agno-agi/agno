"""
Anthropic Code Execution
========================

Cookbook example for `anthropic/code_execution.py`.
"""

from agno.agent import Agent
from agno.models.anthropic import Claude

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Claude(
        id="claude-sonnet-4-20250514",
        betas=["code-execution-2025-05-22"],
    ),
    tools=[
        {
            "type": "code_execution_20250522",
            "name": "code_execution",
        }
    ],
    markdown=True,
)

agent.print_response(
    "Calculate the mean and standard deviation of [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]",
    stream=True,
)

# Show preserved server tool blocks
run_output = agent.get_last_run_output()
print("---" * 5, "Server Tool Blocks", "---" * 5)
for msg in run_output.messages or []:
    if msg.role != "assistant" or not msg.provider_data:
        continue
    for block in msg.provider_data.get("server_tool_blocks", []):
        block_type = block.get("type", "unknown")
        if block_type == "server_tool_use":
            name = block.get("name")
            code = block.get("input", {}).get("code", "")
            print(f"  {block_type}: name={name}, code={code[:80]}...")
        elif block_type == "code_execution_tool_result":
            content = block.get("content", {})
            if isinstance(content, dict):
                print(
                    f"  {block_type}: return_code={content.get('return_code')}, "
                    f"stdout={content.get('stdout', '')[:100]}"
                )
        else:
            print(f"  {block_type}")
print("---" * 20)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
