from pathlib import Path

from agno.agent import Agent
from agno.tools.python import PythonTools

agent = Agent(tools=[PythonTools(base_dir=Path("tmp/python"))], show_tool_calls=True)
agent.print_response(
    "Write a python script for fibonacci series and display the result till the 10th number"
)
