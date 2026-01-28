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
    Compress conversation to WORKING STATE for agent continuity.

    FORMAT:
    TASK: [user's goal in one line]
    STATUS: [In Progress | Blocked | Complete]

    DONE:
    - [tool/search]: [key result summary]

    DATA:
    [Entity/Topic]
    - fact: value (source)
    - fact: value

    SOURCES: [url1], [url2]

    PENDING:
    - [next step]

    PRESERVE ALL (exact values, never paraphrase):
    - Financial: prices ($10/mo, $150M), percentages (15%), ratios (P/E 28.3), ranges (52wk $164-$237)
    - Temporal: dates (Oct 21 2025, Q3 2024), timestamps ([2:30:45]), durations (30min, 3-5 years)
    - Identifiers: URLs, tickers (AAPL), IDs, versions (v2.1), ArXiv IDs
    - Entities: company names, people, products with their attributes
    - Lists: features, ingredients, action items, risk factors
    - Scores: ratings (8/10, 1-9 scale), recommendations (BUY/HOLD/SELL), priorities (HIGH/LOW)
    - Relationships: acquired by, competes with, founded by, integrates with
    - Status: complete/pending, available/deprecated, in stock
    - Geographic: locations, regions, addresses, coordinates
    - Technical: code snippets (<10 lines), SQL, API specs, schemas
    - Citations: paper titles, sources, quotes, methodology

    REMOVE:
    - Narrative descriptions ("researched the company" -> just list facts)
    - Hedging ("might", "possibly", "appears to")
    - Introductions, conclusions, meta-commentary
    - Formatting artifacts (markdown, HTML, JSON structure)
    - Background info not directly relevant to task

    EXAMPLE (Investment Research):
    TASK: Analyze Apple vs Microsoft for investment
    STATUS: In Progress

    DONE:
    - search(AAPL financials): Q3 2024 data
    - search(MSFT financials): Q3 2024 data

    DATA:
    [Apple - AAPL]
    - price: $234.56, 52wk: $164-$237
    - P/E: 28.3, market_cap: $3.5T
    - revenue: $394B (2023), net_income: $99.8B
    - recommendation: BUY, conviction: 8/10

    [Microsoft - MSFT]
    - price: $378.91, 52wk: $309-$384
    - P/E: 32.1, market_cap: $2.8T
    - revenue: $211B (2023), net_income: $72.4B
    - recommendation: BUY, conviction: 9/10

    SOURCES: finance.yahoo.com, SEC filings

    PENDING:
    - Risk assessment comparison
    - Valuation analysis (DCF)

    EXAMPLE (Video Analysis):
    TASK: Extract highlight clips from tutorial video
    STATUS: In Progress

    DONE:
    - analyze(video.mp4): found 5 segments

    DATA:
    [Segments]
    - 0:15-0:45: intro hook, score=8/10
    - 2:30-3:15: key demo, score=9/10
    - 5:00-5:30: summary, score=7/10

    PENDING:
    - Extract top 3 clips
    - Add captions

    INCREMENTAL COMPRESSION:
    When given a "Previous summary", merge new information:
    - Keep all facts from previous summary unless contradicted by new info
    - Add new facts from the conversation
    - Update STATUS and PENDING based on latest state
    - Remove duplicates (same fact should not appear twice)
    """)
