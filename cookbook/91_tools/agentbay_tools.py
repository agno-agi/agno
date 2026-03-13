"""
Agent with AgentBay tools.

This example shows how to use Agno's AgentBay integration to run agent-generated
code in a remote cloud sandbox (code_latest image). AgentBay also supports
linux_latest, browser_latest, and mobile_latest for shell, browser, and mobile automation.

1. Register an Alibaba Cloud account: https://aliyun.com
2. Get API key credentials from the AgentBay Console.
3. Set the environment variable (Linux/MacOS):
    export AGENTBAY_API_KEY=your_api_key_here
4. Install the dependencies:
    pip install agno[agentbay]
   or: uv pip install agno[agentbay]
"""

from agno.agent import Agent
from agno.tools.agentbay import AgentBayTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    name="Coding Agent with AgentBay tools",
    tools=[
        AgentBayTools(
            enable_code_execution=True,
            enable_file_operations=True,
            default_environment="code_latest",
        )
    ],
    markdown=True,
    instructions=[
        "You are an expert at writing and executing code. You have access to a remote AgentBay sandbox (code_latest).",
        "Your primary purpose is to:",
        "1. Write clear, efficient code based on user requests",
        "2. ALWAYS execute the code in the AgentBay sandbox using run_code (call create_sandbox first if needed)",
        "3. Show the actual execution results to the user",
        "4. Provide explanations of how the code works and what the output means",
        "Guidelines:",
        "- NEVER just provide code without executing it",
        "- Call create_sandbox(environment='code_latest') first, then use the returned sandbox_id for run_code",
        "- Execute all code using the run_code tool to show real results",
        "- Support Python and JavaScript execution",
        "- Use file operations (create_file, read_file) when working with scripts",
        "- Always show both the code AND the execution output",
        "- Handle errors gracefully and explain any issues encountered",
    ],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Write Python code to generate 10 random integers between 1 and 100, "
        "sort them in ascending order, and print each number on its own line."
    )
