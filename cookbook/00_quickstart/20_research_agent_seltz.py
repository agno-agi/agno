"""AI Research Agent using Seltz.

This example shows how to create a research agent by combining Seltz search with
report writing to produce a fact-focused, reference-backed output.

Run `pip install openai seltz agno` to install dependencies.
"""

from pathlib import Path
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.seltz import SeltzTools

cwd = Path(__file__).parent.resolve()
tmp = cwd.joinpath("tmp")
tmp.mkdir(exist_ok=True, parents=True)

agent = Agent(
    model=OpenAIChat(id="gpt-5.2"),
    tools=[SeltzTools(max_documents=10, show_results=True)],
    description=dedent(
        """\
        You are an AI research assistant.
        Use Seltz search results to write a clear, factual report with references.
        """
    ),
    instructions=dedent(
        """\
        For the provided topic:
        - Run 3 distinct searches.
        - Cross-check claims across sources.
        - Prefer primary sources and reputable publications.
        - Include a References section with links.
        """
    ),
    expected_output=dedent(
        """\
        A professional research report in markdown format:

        # {Compelling Title}

        ## Executive Summary
        {Brief overview of key findings}

        ## Findings
        {Detailed findings with citations}

        ## Key Takeaways
        - {Takeaway 1}
        - {Takeaway 2}
        - {Takeaway 3}

        ## References
        - [Source 1](link)
        - [Source 2](link)
        - [Source 3](link)
        """
    ),
    markdown=True,
    add_datetime_to_context=True,
    save_response_to_file=str(tmp.joinpath("{message}.md")),
)

if __name__ == "__main__":
    agent.print_response("Research recent advances in AI safety", stream=True)
