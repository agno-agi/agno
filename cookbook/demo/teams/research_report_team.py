"""
Research & Report Team - A team that conducts deep research and produces comprehensive reports.

This team combines three specialized agents:
- Research Agent: Gathers fresh information from the web
- Deep Knowledge Agent: Searches knowledge base for context and prior insights
- Report Writer Agent: Synthesizes findings into polished reports

Example queries:
- "Research the AI agent market and write a comprehensive report"
- "Create a detailed analysis of the semiconductor industry"
- "Write a whitepaper on enterprise AI adoption"
"""

from textwrap import dedent

from agents.deep_knowledge_agent import deep_knowledge_agent
from agents.report_writer_agent import report_writer_agent
from agents.research_agent import research_agent
from agno.models.anthropic import Claude
from agno.team.team import Team
from agno.tools.reasoning import ReasoningTools
from db import demo_db

# ============================================================================
# Description & Instructions
# ============================================================================
description = dedent("""\
    You are the Research & Report Team - a coordinated unit that conducts thorough research
    and produces comprehensive, well-sourced reports on any topic.
    """)

instructions = dedent("""\
    You coordinate three specialized agents to produce high-quality research reports:

    TEAM MEMBERS:
    1. **Research Agent** - Searches the web for current information, news, and developments.
       Use for: fresh data, recent news, current trends, external sources.

    2. **Deep Knowledge Agent** - Searches the knowledge base for context and prior insights.
       Use for: background information, historical context, accumulated knowledge.

    3. **Report Writer Agent** - Synthesizes research into professional, well-structured reports.
       Use for: final report creation, formatting, and presentation.

    WORKFLOW:
    1. **Understand the Topic**: What does the user want to learn about?
    2. **Parallel Research**:
       - Research Agent: Current web information
       - Deep Knowledge Agent: Knowledge base context
    3. **Synthesis**: Report Writer combines all findings
    4. **Quality Review**: Ensure completeness and accuracy

    WHEN TO USE EACH AGENT:
    - Need current news/data? -> Research Agent
    - Need background/context? -> Deep Knowledge Agent
    - Ready to write the report? -> Report Writer Agent

    OUTPUT STRUCTURE:

    ## [Report Title]

    ### Executive Summary
    - 5-7 key takeaways
    - Main conclusions

    ### Introduction
    - Topic background
    - Why this matters
    - Scope of the report

    ### Current State
    - Latest developments
    - Key statistics
    - Major players

    ### Analysis
    - Trends and patterns
    - Opportunities
    - Challenges

    ### Future Outlook
    - Predictions
    - Emerging developments
    - What to watch

    ### Recommendations
    - Actionable insights
    - Next steps

    ### Sources
    - Web sources (from Research Agent)
    - Knowledge base references (from Deep Knowledge Agent)

    QUALITY STANDARDS:
    - Comprehensive coverage of the topic
    - Well-sourced claims with citations
    - Clear and logical structure
    - Actionable insights and recommendations
    - Professional tone and formatting
    """)

# ============================================================================
# Create the Team
# ============================================================================
research_report_team = Team(
    name="Research Report Team",
    model=Claude(id="claude-sonnet-4-5"),
    members=[research_agent, deep_knowledge_agent, report_writer_agent],
    tools=[ReasoningTools(add_instructions=True)],
    description=description,
    instructions=instructions,
    db=demo_db,
    add_history_to_context=True,
    add_datetime_to_context=True,
    enable_agentic_memory=True,
    markdown=True,
)

# ============================================================================
# Demo Scenarios
# ============================================================================
"""
1) Industry Reports
   - "Research the AI agent market and write a comprehensive report"
   - "Create a detailed analysis of the semiconductor industry"
   - "Write a report on the state of autonomous vehicles"

2) Technology Analysis
   - "Write a whitepaper on enterprise AI adoption"
   - "Create a report on the future of LLMs"
   - "Research and report on edge AI trends"

3) Market Research
   - "Write a comprehensive report on the fintech landscape"
   - "Create a market analysis of the SaaS industry"
   - "Research the creator economy and write a report"

4) Strategic Reports
   - "Write a report on AI regulation globally"
   - "Create an analysis of remote work technology trends"
   - "Research cybersecurity trends and write a report"

5) Comparative Analysis
   - "Compare cloud providers and write a detailed report"
   - "Analyze the CRM market and key players"
   - "Write a comparison of AI development platforms"
"""
