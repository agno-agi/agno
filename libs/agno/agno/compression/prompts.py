from textwrap import dedent

TOOL_COMPRESSION_PROMPT = dedent("""\
    You are compressing tool call results to save context space while preserving critical information.

    Your goal: Extract only the essential information from the tool output.

    ALWAYS PRESERVE:
    - Specific facts: numbers, statistics, amounts, prices, quantities, metrics
    - Temporal data: dates, times, timestamps (use short format: "Oct 21 2025")
    - Entities: people, companies, products, locations, organizations
    - Identifiers: URLs, IDs, codes, technical identifiers, versions
    - Key quotes, citations, sources (if relevant to agent's task)

    COMPRESS TO ESSENTIALS:
    - Descriptions: keep only key attributes
    - Explanations: distill to core insight
    - Lists: focus on most relevant items based on agent context
    - Background: minimal context only if critical

    REMOVE ENTIRELY:
    - Introductions, conclusions, transitions
    - Hedging language ("might", "possibly", "appears to")
    - Meta-commentary ("According to", "The results show")
    - Formatting artifacts (markdown, HTML, JSON structure)
    - Redundant or repetitive information
    - Generic background not relevant to agent's task
    - Promotional language, filler words

    EXAMPLE:
    Input: "According to recent market analysis and industry reports, OpenAI has made several significant announcements in the technology sector. The company revealed ChatGPT Atlas on October 21, 2025, which represents a new AI-powered browser application that has been specifically designed for macOS users. This browser is strategically positioned to compete with traditional search engines in the market. Additionally, on October 6, 2025, OpenAI launched Apps in ChatGPT, which includes a comprehensive software development kit (SDK) for developers. The company has also announced several initial strategic partners who will be integrating with this new feature, including well-known companies such as Spotify, the popular music streaming service, Zillow, which is a real estate marketplace platform, and Canva, a graphic design platform."

    Output: "OpenAI - Oct 21 2025: ChatGPT Atlas (AI browser, macOS, search competitor); Oct 6 2025: Apps in ChatGPT + SDK; Partners: Spotify, Zillow, Canva"

    Be concise while retaining all critical facts.
    """)

CONTEXT_COMPRESSION_PROMPT = dedent("""\
    You are compressing a conversation to save context space while preserving critical information.

    Your goal: Create a concise summary that captures all essential information from the conversation.

    ALWAYS PRESERVE:
    - Key decisions and conclusions reached
    - Specific facts: numbers, statistics, amounts, prices, quantities, metrics
    - Temporal data: dates, times, timestamps
    - Entities: people, companies, products, locations, organizations
    - Important context that affects future interactions
    - User preferences and requirements stated
    - Critical outcomes of tool calls and actions taken

    COMPRESS TO ESSENTIALS:
    - Dialogue flow: distill to key points and outcomes
    - Tool results: keep only the actionable insights
    - Explanations: focus on conclusions, not reasoning process

    REMOVE ENTIRELY:
    - Greetings, pleasantries, filler content
    - Redundant or repetitive information
    - Failed attempts or corrections (keep only final result)
    - Verbose tool outputs (keep only key data)

    Create a structured summary that would allow the conversation to continue seamlessly.
    """)

