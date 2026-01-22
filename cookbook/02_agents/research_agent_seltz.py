"""Research Scholar Agent using Seltz search.

Run `pip install openai seltz agno` to install dependencies.
"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.seltz import SeltzTools

# Initialize the research agent with Seltz search
research_scholar = Agent(
    model=OpenAIChat(id="gpt-5.2"),
    tools=[SeltzTools(max_documents=10, show_results=True)],
    description=dedent(
        """\
        You are a distinguished research scholar with expertise in multiple disciplines.
        Combine strong literature search with clear, citation-backed writing.\
        """
    ),
    instructions=dedent(
        """\
        1. Research Methodology
           - Conduct 3 distinct searches
           - Prioritize recent, credible sources
           - Identify key researchers and institutions

        2. Analysis Framework
           - Synthesize findings across sources
           - Evaluate methodologies and consensus
           - Highlight controversies and gaps

        3. Report Structure
           - Create an engaging title and abstract
           - Present methodology and findings clearly
           - Provide evidence-based conclusions

        4. Quality Standards
           - Ensure accurate citations
           - Maintain rigor and balanced perspectives\
        """
    ),
    expected_output=dedent(
        """\
        # {Engaging Title}

        ## Abstract
        {Concise overview of the research and key findings}

        ## Introduction
        {Context and significance}
        {Research objectives}

        ## Methodology
        {Search strategy}
        {Selection criteria}

        ## Literature Review
        {Current state of research}
        {Key findings and breakthroughs}
        {Emerging trends}

        ## Analysis
        {Critical evaluation}
        {Cross-study comparisons}
        {Research gaps}

        ## Future Directions
        {Emerging research opportunities}
        {Potential applications}
        {Open questions}

        ## Conclusions
        {Summary of key findings}
        {Implications for the field}

        ## References
        {Properly formatted academic citations}

        ---
        Research conducted by AI Academic Scholar
        Published: {current_date}
        Last Updated: {current_time}\
        """
    ),
    markdown=True,
    add_datetime_to_context=True,
    save_response_to_file="tmp/{message}.md",
)

# Example usage with research request
if __name__ == "__main__":
    research_scholar.print_response(
        "Analyze recent developments in quantum computing architectures",
        stream=True,
    )
