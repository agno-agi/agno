"""
Deep Research Workflow - A sophisticated 4-phase research workflow.

This workflow produces research quality approaching professional analysts:
1. Topic Decomposition - Break research topic into sub-questions
2. Parallel Research - Research each sub-question from multiple sources
3. Fact Verification - Cross-reference and validate findings
4. Report Synthesis - Create comprehensive final report

Example queries:
- "Deep research: What's the future of AI agents in enterprise?"
- "Comprehensive research on climate tech investment opportunities"
- "In-depth analysis of the LLM landscape in 2025"
"""

from textwrap import dedent
from typing import Dict, List, Optional

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.tools.parallel import ParallelTools
from agno.tools.reasoning import ReasoningTools
from agno.workflow import Step, Workflow
from agno.workflow.parallel import Parallel
from agno.workflow.step import StepInput, StepOutput
from db import demo_db

# ============================================================================
# Phase 1: Topic Decomposition Agent
# ============================================================================
decomposition_agent = Agent(
    name="Topic Decomposer",
    role="Break down research topics into sub-questions",
    model=OpenAIChat(id="gpt-5-mini"),
    tools=[ReasoningTools(add_instructions=True)],
    description=dedent("""\
        You are a research strategist who breaks down complex topics into
        well-structured sub-questions that can be researched independently.
        """),
    instructions=dedent("""\
        Given a research topic, decompose it into 3-5 key sub-questions that:
        1. Cover the most important aspects of the topic
        2. Can be researched independently
        3. Together provide a comprehensive understanding

        Output format:
        ## Research Plan for: [Topic]

        ### Sub-Questions to Investigate:
        1. [Sub-question 1] - Why this matters
        2. [Sub-question 2] - Why this matters
        3. [Sub-question 3] - Why this matters
        ...

        ### Key Terms to Search:
        - [Term 1]
        - [Term 2]
        ...

        ### Expected Sources:
        - Industry reports
        - News articles
        - Expert opinions
        - Data/statistics
        """),
    markdown=True,
    db=demo_db,
)

# ============================================================================
# Phase 2: Research Agents (run in parallel)
# ============================================================================
hn_researcher = Agent(
    name="HN Researcher",
    role="Research trending topics and discussions on Hacker News",
    model=OpenAIChat(id="gpt-5-mini"),
    tools=[HackerNewsTools()],
    description=dedent("""\
        You search Hacker News for relevant discussions, expert opinions,
        and technical insights from the developer and tech community.
        """),
    instructions=dedent("""\
        Search Hacker News for relevant stories and discussions on the given topic.
        Focus on:
        - Highly-voted stories and comments
        - Technical insights and expert opinions
        - Contrarian views and debates
        - Recent developments and announcements

        Summarize findings with:
        - Key themes from the community
        - Notable expert opinions
        - Links to relevant discussions
        """),
    add_history_to_context=True,
    markdown=True,
    db=demo_db,
)

web_researcher = Agent(
    name="Web Researcher",
    role="Search the web for current information and sources",
    model=OpenAIChat(id="gpt-5-mini"),
    tools=[DuckDuckGoTools()],
    description=dedent("""\
        You search the web for up-to-date information, news articles,
        and credible sources on any topic.
        """),
    instructions=dedent("""\
        Search the web for recent and relevant information on the given topic.
        Prioritize:
        - News from last 6 months
        - Credible sources (major publications, official sources)
        - Diverse perspectives

        Summarize findings with:
        - Key facts and statistics
        - Recent developments
        - Expert quotes and opinions
        - Source citations
        """),
    add_history_to_context=True,
    markdown=True,
    db=demo_db,
)

parallel_researcher = Agent(
    name="Deep Researcher",
    role="Perform deep semantic search for high-quality content",
    model=OpenAIChat(id="gpt-5-mini"),
    tools=[ParallelTools(enable_search=True, enable_extract=True)],
    description=dedent("""\
        You use semantic search to find high-quality, in-depth content
        from authoritative sources across the web.
        """),
    instructions=dedent("""\
        Use Parallel's search and extract tools to find highly relevant content.
        Focus on:
        - Authoritative sources (research papers, industry reports)
        - In-depth articles and analysis
        - Expert analysis and predictions
        - Data and statistics

        Summarize findings with:
        - Key insights and analysis
        - Data points and statistics
        - Expert predictions
        - Source links
        """),
    add_history_to_context=True,
    markdown=True,
    db=demo_db,
)

# ============================================================================
# Phase 3: Fact Verification Agent
# ============================================================================
verification_agent = Agent(
    name="Fact Verifier",
    role="Cross-reference and validate research findings",
    model=Claude(id="claude-sonnet-4-5"),
    tools=[ReasoningTools(add_instructions=True)],
    description=dedent("""\
        You analyze research findings to identify consensus, contradictions,
        and areas of uncertainty.
        """),
    instructions=dedent("""\
        Analyze the research findings and:
        1. Identify claims that are well-supported (multiple sources)
        2. Flag contradictions between sources
        3. Note areas of uncertainty or limited data
        4. Highlight the strongest, most reliable insights

        Output format:
        ## Verification Summary

        ### High Confidence Findings
        (Claims with multiple supporting sources)

        ### Moderate Confidence Findings
        (Claims with limited but credible support)

        ### Conflicting Information
        (Where sources disagree)

        ### Data Gaps
        (Important questions that lack sufficient data)
        """),
    add_history_to_context=True,
    markdown=True,
    db=demo_db,
)

# ============================================================================
# Phase 4: Report Synthesis Agent
# ============================================================================
synthesis_agent = Agent(
    name="Report Synthesizer",
    role="Create comprehensive research reports",
    model=Claude(id="claude-sonnet-4-5"),
    tools=[ReasoningTools(add_instructions=True)],
    description=dedent("""\
        You synthesize research findings into clear, comprehensive,
        and actionable reports.
        """),
    instructions=dedent("""\
        Create a comprehensive research report from the findings.

        Report Structure:
        ## Executive Summary
        - 5-7 bullet points capturing key insights

        ## Background
        - Context and why this matters

        ## Key Findings
        - Organized by theme
        - Supported by evidence
        - Clear and specific

        ## Analysis
        - Trends and patterns
        - Implications
        - Expert perspectives

        ## Opportunities & Risks
        - What this means for stakeholders

        ## Conclusion
        - Summary of most important points
        - Recommended next steps

        ## Sources
        - Key sources cited

        Quality Standards:
        - Be specific with data and statistics
        - Cite sources for claims
        - Acknowledge uncertainty
        - Provide actionable insights
        """),
    add_history_to_context=True,
    markdown=True,
    db=demo_db,
)


# ============================================================================
# Workflow Step Functions
# ============================================================================
async def consolidate_research_step_function(input: StepInput) -> StepOutput:
    """Consolidate research from parallel agents into a single document."""
    previous_step_outputs: Optional[Dict[str, StepOutput]] = input.previous_step_outputs

    # Get the parallel research outputs
    parallel_output: Optional[StepOutput] = (
        previous_step_outputs.get("Research Phase") if previous_step_outputs else None
    )

    parallel_steps: Optional[List[StepOutput]] = (
        parallel_output.steps if parallel_output else None
    )

    # Combine all research
    research_content = "## Consolidated Research Findings\n\n"
    research_content += (
        "Use these findings to verify facts and create the final report.\n\n"
    )

    if parallel_steps and len(parallel_steps) > 0:
        for step_output in parallel_steps:
            research_content += f"### From {step_output.step_name}\n\n"
            research_content += f"{step_output.content}\n\n"
            research_content += "---\n\n"

        return StepOutput(content=research_content, success=True)

    return StepOutput(content="No research content found", success=False)


# ============================================================================
# Create Workflow Steps
# ============================================================================
decomposition_step = Step(
    name="Topic Decomposition",
    agent=decomposition_agent,
)

hn_research_step = Step(
    name="HN Research",
    agent=hn_researcher,
)

web_research_step = Step(
    name="Web Research",
    agent=web_researcher,
)

deep_research_step = Step(
    name="Deep Research",
    agent=parallel_researcher,
)

consolidation_step = Step(
    name="Consolidate Research",
    executor=consolidate_research_step_function,
)

verification_step = Step(
    name="Fact Verification",
    agent=verification_agent,
)

synthesis_step = Step(
    name="Report Synthesis",
    agent=synthesis_agent,
)

# ============================================================================
# Create the Workflow
# ============================================================================
deep_research_workflow = Workflow(
    name="Deep Research Workflow",
    description=dedent("""\
        A sophisticated 4-phase research workflow that:
        1. Decomposes topics into sub-questions
        2. Researches from multiple sources in parallel
        3. Verifies and cross-references findings
        4. Synthesizes into a comprehensive report
        """),
    steps=[
        decomposition_step,
        Parallel(
            hn_research_step,
            web_research_step,
            deep_research_step,
            name="Research Phase",
        ),  # type: ignore
        consolidation_step,
        verification_step,
        synthesis_step,
    ],
    db=demo_db,
)

# ============================================================================
# Demo Scenarios
# ============================================================================
"""
1) Technology Trends
   - "Deep research: What's the future of AI agents in enterprise?"
   - "In-depth analysis of the LLM landscape in 2025"
   - "Comprehensive research on quantum computing progress"

2) Industry Analysis
   - "Comprehensive research on climate tech investment opportunities"
   - "Deep dive: The state of autonomous vehicles in 2025"
   - "Research the fintech disruption of traditional banking"

3) Market Research
   - "In-depth research: Is AI in a bubble?"
   - "Comprehensive analysis of the semiconductor supply chain"
   - "Deep research on the creator economy"

4) Strategic Research
   - "Research how enterprises are adopting AI agents"
   - "Deep dive: The future of work with AI"
   - "Comprehensive research on AI regulation globally"
"""
