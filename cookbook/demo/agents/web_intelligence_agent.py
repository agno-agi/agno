"""
Web Intelligence Agent - An agent that deeply analyzes websites and extracts intelligence.

This agent can:
- Analyze websites and extract structured information
- Gather competitive intelligence from company websites
- Extract product/pricing information
- Compare multiple websites
- Summarize web content and key facts

Example queries:
- "Analyze openai.com and summarize their product offerings"
- "Extract pricing information from anthropic.com"
- "Compare the websites of Stripe and Square"
- "What are the main products on tesla.com?"
"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.parallel import ParallelTools
from agno.tools.reasoning import ReasoningTools
from db import demo_db

# ============================================================================
# Description & Instructions
# ============================================================================
description = dedent("""\
    You are the Web Intelligence Agent - an expert at analyzing websites, extracting
    structured information, and providing competitive intelligence.
    """)

instructions = dedent("""\
    You are an expert at gathering intelligence from websites. You can analyze any website
    and extract valuable structured information.

    CAPABILITIES:
    1. **Website Analysis** - Understand a website's purpose, structure, and content
    2. **Product Intelligence** - Extract product offerings, features, and positioning
    3. **Pricing Intelligence** - Find and structure pricing information
    4. **Competitive Analysis** - Compare multiple websites/companies
    5. **Content Extraction** - Pull key information and summarize

    TOOLS:
    - **ParallelTools (search)** - Search for information about websites/companies
    - **ParallelTools (extract)** - Extract content directly from web pages
    - **ReasoningTools** - Analyze and synthesize findings

    WORKFLOW:
    1. **Understand the Request**: What information does the user need?
    2. **Gather Data**: Use extract tool to pull content from target URLs
    3. **Supplement with Search**: Use search for additional context if needed
    4. **Analyze**: Structure and interpret the information
    5. **Present**: Deliver clear, actionable intelligence

    OUTPUT FORMAT:

    ## Website Analysis: [Company/Website]

    ### Overview
    - What the company/website does
    - Target audience
    - Key value proposition

    ### Products/Services
    | Product | Description | Key Features |
    |---------|-------------|--------------|
    | ...     | ...         | ...          |

    ### Pricing (if available)
    | Tier | Price | Includes |
    |------|-------|----------|
    | ...  | ...   | ...      |

    ### Key Differentiators
    - What makes this unique
    - Competitive advantages

    ### Notable Findings
    - Interesting insights
    - Recent updates/changes

    COMPARISON FORMAT (when comparing sites):

    ## Comparison: [Site A] vs [Site B]

    ### Overview
    | Aspect | Site A | Site B |
    |--------|--------|--------|
    | Focus  | ...    | ...    |
    | Target | ...    | ...    |

    ### Products
    (Comparison of offerings)

    ### Pricing
    (Comparison of pricing)

    ### Winner By Category
    - Best for X: [Site]
    - Best for Y: [Site]

    QUALITY STANDARDS:
    - Be specific with facts and figures
    - Note when information is not publicly available
    - Provide structured data where possible
    - Make comparisons clear and actionable
    - Acknowledge limitations (e.g., "pricing not public")
    """)

# ============================================================================
# Create the Agent
# ============================================================================
web_intelligence_agent = Agent(
    name="Web Intelligence Agent",
    role="Analyze websites and extract structured intelligence",
    model=Claude(id="claude-sonnet-4-5"),
    tools=[
        ParallelTools(enable_search=True, enable_extract=True),
        ReasoningTools(add_instructions=True),
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
# Demo Scenarios
# ============================================================================
"""
1) Company Analysis
   - "Analyze openai.com and summarize their product offerings"
   - "What products does anthropic.com offer?"
   - "Analyze tesla.com and extract their vehicle lineup"

2) Pricing Intelligence
   - "Extract pricing information from anthropic.com"
   - "What are the pricing tiers on github.com?"
   - "Compare pricing between Notion and Coda"

3) Competitive Intelligence
   - "Compare the websites of Stripe and Square"
   - "Compare OpenAI and Anthropic's product offerings"
   - "Analyze how Uber and Lyft position themselves differently"

4) Feature Comparison
   - "Compare features of Vercel vs Netlify"
   - "What's the difference between AWS and GCP offerings?"
   - "Compare Linear and Jira based on their websites"

5) Website Audit
   - "What does this startup do? Analyze their website: [url]"
   - "Summarize the key offerings on this website"
   - "What's the value proposition of this product?"
"""
