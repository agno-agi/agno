"""
Parallel Deep Research - Cited Reports With the Task API
========================================================

The Task API runs deep, multi-step research and returns an answer with a
"basis": the citations and confidence behind the findings. That is the
difference between an answer and an answer you can verify.

The agent calls create_task() to launch the research, then get_task_result()
to retrieve the report plus its sources.

Processors trade depth for time:
- "base"  - fast, good for most questions (seconds to a few minutes)
- "pro"   - deeper, and required for the "auto" output schema
- "ultra" - maximum depth (can run many minutes)

Prerequisites:
- pip install parallel-web
- export PARALLEL_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools

# ---------------------------------------------------------------------------
# Tools - Task API (deep research)
# ---------------------------------------------------------------------------
# A "text" output schema returns a long-form markdown report with inline
# citations. Start with the base processor for a fast first pass.
research_tools = ParallelTools(
    enable_search=False,
    enable_extract=False,
    enable_task=True,
    default_processor="base",
    default_output_schema={"type": "text"},
)

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
research_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[research_tools],
    markdown=True,
    instructions=[
        "Use create_task() to launch deep research, then get_task_result().",
        "Present the findings and list the sources behind each claim.",
    ],
)

# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    research_agent.print_response(
        "Research the current AI web-research API market: who the main "
        "providers are, how they price, and how they differ. Cite sources.",
        stream=True,
    )
