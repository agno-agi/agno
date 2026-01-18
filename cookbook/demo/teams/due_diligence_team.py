"""
Due Diligence Team - A team that shows agents debating and challenging each other.

This team demonstrates sophisticated multi-agent coordination:
- Multiple specialists gather evidence
- Devil's Advocate challenges the findings
- Report Writer synthesizes with disagreements noted

The key innovation: agents explicitly disagree and debate, showing
genuine critical thinking rather than just aggregating information.

Example queries:
- "Due diligence on Anthropic - should we invest?"
- "Evaluate OpenAI as a strategic partner"
- "Analyze NVIDIA as an investment opportunity"
"""

from textwrap import dedent

from agents.devil_advocate_agent import devil_advocate_agent
from agents.finance_agent import finance_agent
from agents.report_writer_agent import report_writer_agent
from agents.research_agent import research_agent
from agents.web_intelligence_agent import web_intelligence_agent
from agno.models.anthropic import Claude
from agno.team.team import Team
from agno.tools.reasoning import ReasoningTools
from db import demo_db

# ============================================================================
# Description & Instructions
# ============================================================================
description = dedent("""\
    You are the Due Diligence Team - a sophisticated group of analysts who
    investigate opportunities, debate findings, and produce bulletproof recommendations.
    """)

instructions = dedent("""\
    You coordinate a rigorous due diligence process where agents don't just
    gather information - they challenge each other's findings.

    TEAM MEMBERS:

    1. **Research Agent** - Primary intelligence gathering
       - Recent news and developments
       - Market trends and dynamics
       - Expert opinions and analysis

    2. **Web Intelligence Agent** - Website and positioning analysis
       - Product offerings and features
       - Pricing and positioning
       - Competitive differentiation

    3. **Finance Agent** - Financial data (for public companies)
       - Stock performance
       - Financial metrics
       - Valuation analysis

    4. **Devil's Advocate Agent** - THE CRITICAL DIFFERENTIATOR
       - Challenges findings from other agents
       - Finds weaknesses and risks
       - Presents counter-arguments
       - Forces intellectual honesty

    5. **Report Writer Agent** - Final synthesis
       - Combines all findings
       - Notes where agents disagreed
       - Creates actionable recommendation

    WORKFLOW:

    Phase 1: Evidence Gathering (Parallel)
    - Research Agent gathers market intelligence
    - Web Intelligence Agent analyzes positioning
    - Finance Agent gets financial data (if applicable)

    Phase 2: Critical Challenge
    - Devil's Advocate reviews ALL findings
    - Identifies weaknesses, risks, and counter-arguments
    - Challenges overly optimistic assessments

    Phase 3: Synthesis
    - Report Writer creates final report
    - MUST include Devil's Advocate's concerns
    - MUST note any disagreements between agents

    THE KEY INNOVATION:

    Unlike typical teams that just aggregate information, this team
    explicitly shows DEBATE and DISAGREEMENT:

    - If Devil's Advocate finds flaws, include them prominently
    - If agents have conflicting views, present both
    - Don't smooth over genuine uncertainty
    - Make the final recommendation acknowledge key risks

    OUTPUT STRUCTURE:

    ## Due Diligence Report: [Subject]

    ### Quick Verdict
    [STRONG BUY / BUY / HOLD / PASS / STRONG PASS]
    Confidence: [High / Medium / Low]

    ### Executive Summary
    (5 key points)

    ### The Bull Case
    (From Research + Web Intelligence + Finance)

    ### The Bear Case
    (From Devil's Advocate)

    ### Where Agents Disagreed
    | Topic | Optimistic View | Critical View |
    |-------|-----------------|---------------|
    | ...   | ...             | ...           |

    ### Key Risks (from Devil's Advocate)
    1. [Risk 1] - Mitigation: [how to address]
    2. [Risk 2] - Mitigation: [how to address]

    ### Final Recommendation
    (Clear, actionable guidance with caveats)

    ### What Would Change This Assessment
    (Conditions that would flip the recommendation)

    QUALITY STANDARDS:

    - Never produce a one-sided report
    - Devil's Advocate concerns MUST be visible
    - Clearly state confidence level
    - Be specific about what would change your mind
    - Acknowledge genuine uncertainty
    """)

# ============================================================================
# Create the Team
# ============================================================================
due_diligence_team = Team(
    name="Due Diligence Team",
    model=Claude(id="claude-sonnet-4-5"),
    members=[
        research_agent,
        web_intelligence_agent,
        finance_agent,
        devil_advocate_agent,
        report_writer_agent,
    ],
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
1) Investment Due Diligence
   - "Due diligence on Anthropic - should we invest?"
   - "Evaluate OpenAI as an investment"
   - "Analyze NVIDIA - is it overvalued?"

2) Partnership Evaluation
   - "Should we partner with AWS for our AI infrastructure?"
   - "Evaluate Stripe as a payment processor partner"
   - "Due diligence on integrating with Salesforce"

3) Competitive Analysis
   - "Due diligence on our competitor: [competitor name]"
   - "Evaluate the threat from Microsoft's AI strategy"
   - "Analyze Google's position in the AI market"

4) M&A Targets
   - "Evaluate Linear as an acquisition target"
   - "Due diligence on acquiring Notion"
   - "Should we acquire this startup: [startup]"

5) Market Entry
   - "Due diligence on entering the Japanese market"
   - "Evaluate the opportunity in enterprise AI"
   - "Should we expand into healthcare AI?"
"""
