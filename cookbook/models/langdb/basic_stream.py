from typing import Iterator  # noqa
from agno.agent import Agent, RunResponse  # noqa
from agno.models.langdb import LangDB

# Option 1: Get project_id from LANGDB_PROJECT_ID environment variable
agent = Agent(
    model=LangDB(id="llama3-1-70b-instruct-v1.0"),  # project_id will be read from env
    markdown=True,
)

# Option 2: Pass project_id directly
# agent = Agent(
#     model=LangDB(
#         id="llama3-1-70b-instruct-v1.0",
#         project_id="your-langdb-project-id"  # This will override env var if set
#     ),
#     markdown=True,
# )

# Get the response in a variable
# run_response: Iterator[RunResponse] = agent.run("Share a 2 sentence horror story", stream=True)
# for chunk in run_response:
#     print(chunk.content)

# Print the response in the terminal
agent.print_response("Share a 2 sentence horror story", stream=True)
