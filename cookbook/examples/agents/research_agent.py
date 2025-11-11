"""🔍 Research Agent - Your AI Investigative Journalist!

This example shows how to create a sophisticated research agent that combines
web search capabilities with professional journalistic writing skills. The agent performs
comprehensive research using multiple sources, fact-checks information, and delivers
well-structured, NYT-style articles on any topic.

Key capabilities:
- Advanced web search across multiple sources
- Content extraction and analysis
- Cross-reference verification
- Professional journalistic writing
- Balanced and objective reporting

Example prompts to try:
- "Analyze the impact of AI on healthcare delivery and patient outcomes"
- "Report on the latest breakthroughs in quantum computing"
- "Investigate the global transition to renewable energy sources"
- "Explore the evolution of cybersecurity threats and defenses"
- "Research the development of autonomous vehicle technology"

Dependencies: `pip install openai ddgs newspaper4k lxml_html_clean agno`
"""

from textwrap import dedent

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.newspaper4k import Newspaper4kTools

# Initialize the research agent with advanced journalistic capabilities
research_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools(), Newspaper4kTools()],
    description=dedent("""\
        You are an elite investigative journalist with decades of experience at the New York Times.
        Your expertise encompasses: 📰

        - Deep investigative research and analysis
        - Meticulous fact-checking and source verification
        - Compelling narrative construction
        - Data-driven reporting and visualization
        - Expert interview synthesis
        - Trend analysis and future predictions
        - Complex topic simplification
        - Ethical journalism practices
        - Balanced perspective presentation
        - Global context integration\
    """),
    instructions=dedent("""\
        1. Research Phase 🔍
           - Search for 10+ authoritative sources on the topic
           - Prioritize recent publications and expert opinions
           - Identify key stakeholders and perspectives

        2. Analysis Phase 📊
           - Extract and verify critical information
           - Cross-reference facts across multiple sources
           - Identify emerging patterns and trends
           - Evaluate conflicting viewpoints

        3. Writing Phase ✍️
           - Craft an attention-grabbing headline
           - Structure content in NYT style
           - Include relevant quotes and statistics
           - Maintain objectivity and balance
           - Explain complex concepts clearly

        4. Quality Control ✓
           - Verify all facts and attributions
           - Ensure narrative flow and readability
           - Add context where necessary
           - Include future implications
    """),
    expected_output=dedent("""\
        # {Compelling Headline} 📰

        ## Executive Summary
        {Concise overview of key findings and significance}

        ## Background & Context
        {Historical context and importance}
        {Current landscape overview}

        ## Key Findings
        {Main discoveries and analysis}
        {Expert insights and quotes}
        {Statistical evidence}

        ## Impact Analysis
        {Current implications}
        {Stakeholder perspectives}
        {Industry/societal effects}

        ## Future Outlook
        {Emerging trends}
        {Expert predictions}
        {Potential challenges and opportunities}

        ## Expert Insights
        {Notable quotes and analysis from industry leaders}
        {Contrasting viewpoints}

        ## Sources & Methodology
        {List of primary sources with key contributions}
        {Research methodology overview}

        ---
        Research conducted by AI Investigative Journalist
        New York Times Style Report
        Published: {current_date}
        Last Updated: {current_time}\
    """),
    db=SqliteDb(db_file="tmp/research_agent.db"),
    num_history_runs=2,
    markdown=True,
    add_datetime_to_context=True,
    add_history_to_context=True,
    max_tool_calls_from_history=5,
    debug_mode=True,
)

# Example usage with detailed research request
if __name__ == "__main__":
    research_agent.print_response(
        "Analyze the current state and future implications of artificial intelligence regulation worldwide",
        stream=True,
    )
    research_agent.print_response(
        "Research the current state of quantum computing and its practical applications",
        stream=True,
    )
    research_agent.print_response(
        "Explore the latest developments in CRISPR gene editing technology",
        stream=True,
    )
    research_agent.print_response(
        "Report on innovative carbon capture technologies and their effectiveness",
        stream=True,
    )
    research_agent.print_response(
        "Investigate the global progress in renewable energy adoption",
        stream=True,
    )
    research_agent.print_response(
        "Examine the effects of social media on democratic processes",
        stream=True,
    )

# Advanced research topics to explore:
"""
Technology & Innovation:
1. "Investigate the development and impact of large language models in 2024"
2. "Research the current state of quantum computing and its practical applications"
3. "Analyze the evolution and future of edge computing technologies"
4. "Explore the latest advances in brain-computer interface technology"

Environmental & Sustainability:
1. "Report on innovative carbon capture technologies and their effectiveness"
2. "Investigate the global progress in renewable energy adoption"
3. "Analyze the impact of circular economy practices on global sustainability"
4. "Research the development of sustainable aviation technologies"

Healthcare & Biotechnology:
1. "Explore the latest developments in CRISPR gene editing technology"
2. "Analyze the impact of AI on drug discovery and development"
3. "Investigate the evolution of personalized medicine approaches"
4. "Research the current state of longevity science and anti-aging research"

Societal Impact:
1. "Examine the effects of social media on democratic processes"
2. "Analyze the impact of remote work on urban development"
3. "Investigate the role of blockchain in transforming financial systems"
4. "Research the evolution of digital privacy and data protection measures"
"""
