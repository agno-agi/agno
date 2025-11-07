"""
Memo Writer Agent - Executive Investment Brief Generation

Transforms financial analysis into professional investment memoranda
for C-level stakeholders with clear recommendations.
"""

import os
from datetime import datetime
from agno.agent import Agent
from agno.models.google import Gemini


MemoWriter = Agent(
    name="Memo Writer",
    model=Gemini(id="gemini-2.5-flash", api_key=os.getenv("GEMINI_API_KEY")),
    instructions=[
        "Senior investment strategist. Create executive investment briefs.",
        f"Date: {datetime.now().strftime('%B %d, %Y')} - use exact date.",
        "",
        "Create a professional investment memo with:",
        "1. Header: Investment Brief: [Company] ([TICKER]) - Date: [TODAY]",
        "2. Executive Summary (3-4 key insights and recommendation)",
        "3. Investment Recommendation (BUY/HOLD/SELL with price target)",
        "4. Key Investment Drivers (3-5 compelling reasons)",
        "5. Risk Factors (2-3 main risks)",
        "6. Financial Highlights (current price, target, market cap)",
        "",
        "CRITICAL PRICING REQUIREMENTS:",
        "- Use the EXACT current_price from the valuation data provided",
        "- DO NOT make up or estimate prices",
        "- Display prices with 2 decimal places (e.g., $452.42)",
        "- Ensure current price matches the real-time quote data",
        "",
        "Writing style:",
        "- Maximum 2 pages, concise and impactful",
        "- Professional tone for C-level executives",
        "- Use bullet points and clear headings",
        "- Include specific numbers and percentages",
        "- Format as professional markdown"
    ]
)


