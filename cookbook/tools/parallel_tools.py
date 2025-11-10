"""
This is an example of how to use the ParallelTools Toolkit.

Prerequisites:
- Create a Parallel account at https://platform.parallel.ai and get an API key
- Set the API key as an environment variable:
    export PARALLEL_API_KEY=<your-api-key>
- Install the parallel-web package:
    pip install parallel-web
"""

from agno.agent import Agent
from agno.tools.parallel import ParallelTools

agent = Agent(
    tools=[
        ParallelTools(
            enable_search=True,
            enable_extract=True,
            max_results=5,
            max_chars_per_result=8000,
        )
    ],
    markdown=True,
)

# Should use parallel_search
agent.print_response(
    "Search for the latest information on 'AI agents and autonomous systems' and summarize the key findings"
)

# Should use parallel_extract
agent.print_response(
    "Extract information about the product features from https://parallel.ai and https://docs.parallel.ai"
)
