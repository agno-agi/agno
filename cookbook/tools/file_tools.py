from pathlib import Path

from agno.agent import Agent
from agno.tools.file import FileTools

agent = Agent(tools=[FileTools(Path("tmp/file"))], show_tool_calls=True)
agent.print_response(
    "What is the most advanced LLM currently? Save the answer to a file.", markdown=True
)

# Example 2: Search for files with a specific extension
# agent.print_response(
#     "Search for all files which have an extension '.txt' and save the answer to a a new file name 'all_txt_files.txt'",
#     markdown=True,
# )
