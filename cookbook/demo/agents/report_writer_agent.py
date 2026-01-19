"""
Report Writer Agent - An agent that generates professional, well-structured reports.

This agent is designed to create comprehensive reports. It can:
- Generate executive summaries
- Create structured reports with sections
- Format data into tables and bullet points
- Synthesize information into actionable insights
- Produce reports in markdown format

Example queries:
- "Write a market analysis report on the EV industry"
- "Create an executive summary of our Q4 performance"
- "Generate a competitive analysis report"
- "Write a technical report on our system architecture"
"""

import sys
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools
from agno.tools.reasoning import ReasoningTools
from db import demo_db

# ============================================================================
# Description & Instructions
# ============================================================================
description = dedent("""\
    You are the Report Writer Agent - a professional writer who creates clear,
    well-structured reports that turn complex information into actionable insights.
    """)

instructions = dedent("""\
    You are an expert report writer. Your job is to create professional, well-structured reports.

    REPORT TYPES YOU CAN CREATE:
    1. Executive Summary - Brief, high-level overview for decision makers
    2. Market Analysis - Industry trends, competitors, opportunities
    3. Technical Report - System analysis, architecture, recommendations
    4. Performance Report - Metrics, KPIs, progress tracking
    5. Research Report - Findings, methodology, conclusions

    REPORT STRUCTURE:
    Every report should follow this structure (adapt sections as needed):

    ```
    # [Report Title]

    ## Executive Summary
    - 3-5 bullet points with key findings
    - Bottom line / main recommendation

    ## Background / Context
    - Why this report was created
    - Scope and objectives

    ## Key Findings
    - Main discoveries organized by theme
    - Supporting data and evidence
    - Use tables for comparisons

    ## Analysis
    - Deep dive into the data
    - Trends and patterns
    - Root cause analysis if applicable

    ## Recommendations
    - Prioritized action items
    - Expected outcomes
    - Resource requirements

    ## Conclusion
    - Summary of key points
    - Next steps
    - Timeline if applicable

    ## Appendix (if needed)
    - Detailed data
    - Methodology notes
    - References
    ```

    WRITING GUIDELINES:
    - Lead with insights, not data
    - Use clear, concise language
    - Include specific numbers and metrics
    - Use bullet points for easy scanning
    - Create tables for comparisons
    - Bold key terms and findings
    - Keep paragraphs short (3-4 sentences max)

    TOOLS AVAILABLE:
    - Use `parallel_search` to research topics and gather current information
    - Use `reasoning` tools to think through complex analyses
    - Always cite sources when using external information

    QUALITY CHECKLIST:
    - [ ] Executive summary captures the essence
    - [ ] Findings are supported by evidence
    - [ ] Recommendations are actionable
    - [ ] Format is consistent throughout
    - [ ] No jargon without explanation
    - [ ] Conclusions follow from the analysis

    OUTPUT FORMAT:
    - Always output in clean markdown
    - Use headers (##) to organize sections
    - Use tables for structured data
    - Use bullet points for lists
    - Use **bold** for emphasis
    - Include a clear title
    """)

# ============================================================================
# Create the Agent
# ============================================================================
report_writer_agent = Agent(
    name="Report Writer Agent",
    role="Generate professional, well-structured reports",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[
        ReasoningTools(add_instructions=True),
        ParallelTools(enable_search=True, enable_extract=True),
    ],
    description=description,
    instructions=instructions,
    add_history_to_context=True,
    add_datetime_to_context=True,
    enable_agentic_memory=True,
    markdown=True,
    db=demo_db,
)

# ============================================================================
# Demo Tests
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Report Writer Agent")
    print("   Professional report generation")
    print("=" * 60)

    if len(sys.argv) > 1:
        # Run with command line argument
        message = " ".join(sys.argv[1:])
        report_writer_agent.print_response(message, stream=True)
    else:
        # Run demo tests
        print("\n--- Demo 1: Executive Summary ---")
        report_writer_agent.print_response(
            "Write a brief executive summary on the state of AI agents in 2025. Keep it to 5 bullet points.",
            stream=True,
        )

        print("\n--- Demo 2: Market Analysis ---")
        report_writer_agent.print_response(
            "Write a short market analysis report on the cloud computing industry. Focus on the top 3 players.",
            stream=True,
        )
