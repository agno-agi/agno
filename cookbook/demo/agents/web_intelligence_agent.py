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
    model=OpenAIResponses(id="gpt-5.2"),
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
# Demo Tests
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Web Intelligence Agent")
    print("   Website analysis and competitive intelligence")
    print("=" * 60)

    if len(sys.argv) > 1:
        # Run with command line argument
        message = " ".join(sys.argv[1:])
        web_intelligence_agent.print_response(message, stream=True)
    else:
        # Run demo tests
        print("\n--- Demo 1: Company Analysis ---")
        web_intelligence_agent.print_response(
            "Analyze anthropic.com - give me a quick summary of what they do and their main products.",
            stream=True,
        )

        print("\n--- Demo 2: Competitive Intel ---")
        web_intelligence_agent.print_response(
            "Compare OpenAI and Anthropic based on their websites - key differences only.",
            stream=True,
        )
