from pathlib import Path

from agno.agent import Agent
from agno.tools.python import PythonTools

# Example 1: All functions available (default behavior)
agent_all = Agent(
    name="Python Agent - All Functions",
    tools=[PythonTools(base_dir=Path("tmp/python"))],
    instructions=["You have access to all Python execution capabilities."],
    markdown=True,
)

# Example 2: Include specific functions only
agent_specific = Agent(
    name="Python Agent - Specific Functions",
    tools=[
        PythonTools(
            base_dir=Path("tmp/python"),
            include_tools=["save_to_file_and_run", "run_python_code"],
        )
    ],
    instructions=["You can only save and run Python code, no package installation."],
    markdown=True,
)

# Example 3: Exclude dangerous functions
agent_safe = Agent(
    name="Python Agent - Safe Mode",
    tools=[
        PythonTools(
            base_dir=Path("tmp/python"),
            exclude_tools=["pip_install_package", "uv_pip_install_package"],
        )
    ],
    instructions=["You can run Python code but cannot install packages."],
    markdown=True,
)

# Use the default agent for examples
agent = agent_all

agent.print_response(
    "Write a python script for fibonacci series and display the result till the 10th number"
)
