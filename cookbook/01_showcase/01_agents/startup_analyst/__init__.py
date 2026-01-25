"""
Startup Analyst
===============

A startup intelligence agent that performs comprehensive due diligence on companies
by scraping their websites, analyzing public information, and producing investment-grade reports.

Example:
    from startup_analyst import startup_analyst, analyze_startup

    # Analyze a startup
    report = analyze_startup("https://anthropic.com")
"""

from startup_analyst.agent import analyze_startup, startup_analyst

__all__ = [
    "startup_analyst",
    "analyze_startup",
]
