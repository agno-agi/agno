"""Investment Report Generator - Your AI Financial Analysis Studio!

This advanced example demonstrates how to build a sophisticated investment analysis system that combines
market research, financial analysis, and portfolio management. The workflow uses a three-stage
approach:
1. Comprehensive stock analysis and market research
2. Investment potential evaluation and ranking
3. Strategic portfolio allocation recommendations

Key capabilities:
- Real-time market data analysis
- Professional financial research
- Investment risk assessment
- Portfolio allocation strategy
- Detailed investment rationale

Example companies to analyze:
- "AAPL, MSFT, GOOGL" (Tech Giants)
- "NVDA, AMD, INTC" (Semiconductor Leaders)
- "TSLA, F, GM" (Automotive Innovation)
- "JPM, BAC, GS" (Banking Sector)
- "AMZN, WMT, TGT" (Retail Competition)
- "PFE, JNJ, MRNA" (Healthcare Focus)
- "XOM, CVX, BP" (Energy Sector)

Run `uv pip install openai yfinance agno` to install dependencies.
"""

import asyncio
import random
from pathlib import Path
from shutil import rmtree
from textwrap import dedent

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.yfinance import YFinanceTools
from agno.utils.pprint import pprint_run_response
from agno.workflow.types import WorkflowExecutionInput
from agno.workflow.workflow import Workflow
from pydantic import BaseModel


# --- Response models ---
class StockAnalysisResult(BaseModel):
    company_symbols: str
    market_analysis: str
    financial_metrics: str
    risk_assessment: str
    recommendations: str


class InvestmentRanking(BaseModel):
    ranked_companies: str
    investment_rationale: str
    risk_evaluation: str
    growth_potential: str


class PortfolioAllocation(BaseModel):
    allocation_strategy: str
    investment_thesis: str
    risk_management: str
    final_recommendations: str


# --- File management ---
reports_dir = Path(__file__).parent.joinpath("reports", "investment")
if reports_dir.is_dir():
    rmtree(path=reports_dir, ignore_errors=True)
reports_dir.mkdir(parents=True, exist_ok=True)

stock_analyst_report = str(reports_dir.joinpath("stock_analyst_report.md"))
research_analyst_report = str(reports_dir.joinpath("research_analyst_report.md"))
investment_report = str(reports_dir.joinpath("investment_report.md"))


# --- Agents ---
stock_analyst = Agent(
    name="Stock Analyst",
    model=OpenAIChat(id="gpt-4o"),
    tools=[YFinanceTools()],
    description=dedent("""\
    You are MarketMaster-X, an elite Senior Investment Analyst at Goldman Sachs with expertise in:

    - Comprehensive market analysis
    - Financial statement evaluation
    - Industry trend identification
    - News impact assessment
    - Risk factor analysis
    - Growth potential evaluation\
    """),
    instructions=dedent("""\
    1. Market Research
       - Analyze company fundamentals and metrics
       - Review recent market performance
       - Evaluate competitive positioning
       - Assess industry trends and dynamics
    2. Financial Analysis
       - Examine key financial ratios
       - Review analyst recommendations
       - Analyze recent news impact
       - Identify growth catalysts
    3. Risk Assessment
       - Evaluate market risks
       - Assess company-specific challenges
       - Consider macroeconomic factors
       - Identify potential red flags
    Note: This analysis is for educational purposes only.\
    """),
    output_schema=StockAnalysisResult,
)

research_analyst = Agent(
    name="Research Analyst",
    model=OpenAIChat(id="gpt-4o"),
    description=dedent("""\
    You are ValuePro-X, an elite Senior Research Analyst at Goldman Sachs specializing in:

    - Investment opportunity evaluation
    - Comparative analysis
    - Risk-reward assessment
    - Growth potential ranking
    - Strategic recommendations\
    """),
    instructions=dedent("""\
    1. Investment Analysis
       - Evaluate each company's potential
       - Compare relative valuations
       - Assess competitive advantages
       - Consider market positioning
    2. Risk Evaluation
       - Analyze risk factors
       - Consider market conditions
       - Evaluate growth sustainability
       - Assess management capability
    3. Company Ranking
       - Rank based on investment potential
       - Provide detailed rationale
       - Consider risk-adjusted returns
       - Explain competitive advantages\
    """),
    output_schema=InvestmentRanking,
)

investment_lead = Agent(
    name="Investment Lead",
    model=OpenAIChat(id="gpt-4o"),
    description=dedent("""\
    You are PortfolioSage-X, a distinguished Senior Investment Lead at Goldman Sachs expert in:

    - Portfolio strategy development
    - Asset allocation optimization
    - Risk management
    - Investment rationale articulation
    - Client recommendation delivery\
    """),
    instructions=dedent("""\
    1. Portfolio Strategy
       - Develop allocation strategy
       - Optimize risk-reward balance
       - Consider diversification
       - Set investment timeframes
    2. Investment Rationale
       - Explain allocation decisions
       - Support with analysis
       - Address potential concerns
       - Highlight growth catalysts
    3. Recommendation Delivery
       - Present clear allocations
       - Explain investment thesis
       - Provide actionable insights
       - Include risk considerations\
    """),
    output_schema=PortfolioAllocation,
)


# --- Execution function ---
async def investment_analysis_execution(
    execution_input: WorkflowExecutionInput,
    companies: str,
) -> str:
    """Execute the complete investment analysis workflow"""

    # Get inputs
    message: str = execution_input.input
    company_symbols: str = companies

    if not company_symbols:
        return "No company symbols provided"

    print(f"Starting investment analysis for companies: {company_symbols}")
    print(f"Analysis request: {message}")

    # Phase 1: Stock Analysis
    print("\nPHASE 1: COMPREHENSIVE STOCK ANALYSIS")
    print("=" * 60)

    analysis_prompt = f"""
    {message}

    Please conduct a comprehensive analysis of the following companies: {company_symbols}

    For each company, provide:
    1. Current market position and financial metrics
    2. Recent performance and analyst recommendations
    3. Industry trends and competitive landscape
    4. Risk factors and growth potential
    5. News impact and market sentiment
    Companies to analyze: {company_symbols}
    """

    print("Analyzing market data and fundamentals...")
    stock_analysis_result = await stock_analyst.arun(analysis_prompt)
    stock_analysis = stock_analysis_result.content

    # Save to file
    with open(stock_analyst_report, "w") as f:
        f.write("# Stock Analysis Report\n\n")
        f.write(f"**Companies:** {stock_analysis.company_symbols}\n\n")
        f.write(f"## Market Analysis\n{stock_analysis.market_analysis}\n\n")
        f.write(f"## Financial Metrics\n{stock_analysis.financial_metrics}\n\n")
        f.write(f"## Risk Assessment\n{stock_analysis.risk_assessment}\n\n")
        f.write(f"## Recommendations\n{stock_analysis.recommendations}\n")

    print(f"Stock analysis completed and saved to {stock_analyst_report}")

    # Phase 2: Investment Ranking
    print("\nPHASE 2: INVESTMENT POTENTIAL RANKING")
    print("=" * 60)

    ranking_prompt = f"""
    Based on the comprehensive stock analysis below, please rank these companies by investment potential.
    STOCK ANALYSIS:
    - Market Analysis: {stock_analysis.market_analysis}
    - Financial Metrics: {stock_analysis.financial_metrics}
    - Risk Assessment: {stock_analysis.risk_assessment}
    - Initial Recommendations: {stock_analysis.recommendations}
    Please provide:
    1. Detailed ranking of companies from best to worst investment potential
    2. Investment rationale for each company
    3. Risk evaluation and mitigation strategies
    4. Growth potential assessment
    """

    print("Ranking companies by investment potential...")
    ranking_result = await research_analyst.arun(ranking_prompt)
    ranking_analysis = ranking_result.content

    # Save to file
    with open(research_analyst_report, "w") as f:
        f.write("# Investment Ranking Report\n\n")
        f.write(f"## Company Rankings\n{ranking_analysis.ranked_companies}\n\n")
        f.write(f"## Investment Rationale\n{ranking_analysis.investment_rationale}\n\n")
        f.write(f"## Risk Evaluation\n{ranking_analysis.risk_evaluation}\n\n")
        f.write(f"## Growth Potential\n{ranking_analysis.growth_potential}\n")

    print(f"Investment ranking completed and saved to {research_analyst_report}")

    # Phase 3: Portfolio Allocation Strategy
    print("\nPHASE 3: PORTFOLIO ALLOCATION STRATEGY")
    print("=" * 60)

    portfolio_prompt = f"""
    Based on the investment ranking and analysis below, create a strategic portfolio allocation.
    INVESTMENT RANKING:
    - Company Rankings: {ranking_analysis.ranked_companies}
    - Investment Rationale: {ranking_analysis.investment_rationale}
    - Risk Evaluation: {ranking_analysis.risk_evaluation}
    - Growth Potential: {ranking_analysis.growth_potential}
    Please provide:
    1. Specific allocation percentages for each company
    2. Investment thesis and strategic rationale
    3. Risk management approach
    4. Final actionable recommendations
    """

    print("Developing portfolio allocation strategy...")
    portfolio_result = await investment_lead.arun(portfolio_prompt)
    portfolio_strategy = portfolio_result.content

    # Save to file
    with open(investment_report, "w") as f:
        f.write("# Investment Portfolio Report\n\n")
        f.write(f"## Allocation Strategy\n{portfolio_strategy.allocation_strategy}\n\n")
        f.write(f"## Investment Thesis\n{portfolio_strategy.investment_thesis}\n\n")
        f.write(f"## Risk Management\n{portfolio_strategy.risk_management}\n\n")
        f.write(
            f"## Final Recommendations\n{portfolio_strategy.final_recommendations}\n"
        )

    print(f"Portfolio strategy completed and saved to {investment_report}")

    # Final summary
    summary = f"""
    INVESTMENT ANALYSIS WORKFLOW COMPLETED!

    Analysis Summary:
    - Companies Analyzed: {company_symbols}
    - Market Analysis: Completed
    - Investment Ranking: Completed
    - Portfolio Strategy: Completed

    Reports Generated:
    - Stock Analysis: {stock_analyst_report}
    - Investment Ranking: {research_analyst_report}
    - Portfolio Strategy: {investment_report}

    Key Insights:
    {portfolio_strategy.allocation_strategy[:200]}...

    Disclaimer: This analysis is for educational purposes only and should not be considered as financial advice.
    """

    return summary


# --- Workflow definition ---
investment_workflow = Workflow(
    name="Investment Report Generator",
    description="Automated investment analysis with market research and portfolio allocation",
    db=SqliteDb(
        session_table="workflow_session",
        db_file="tmp/workflows.db",
    ),
    steps=investment_analysis_execution,
    session_state={},  # Initialize empty workflow session state
)


if __name__ == "__main__":

    async def main():
        from rich.prompt import Prompt

        # Example investment scenarios to showcase the analyzer's capabilities
        example_scenarios = [
            "AAPL, MSFT, GOOGL",  # Tech Giants
            "NVDA, AMD, INTC",  # Semiconductor Leaders
            "TSLA, F, GM",  # Automotive Innovation
            "JPM, BAC, GS",  # Banking Sector
            "AMZN, WMT, TGT",  # Retail Competition
            "PFE, JNJ, MRNA",  # Healthcare Focus
            "XOM, CVX, BP",  # Energy Sector
        ]

        # Get companies from user with example suggestion
        companies = Prompt.ask(
            "[bold]Enter company symbols (comma-separated)[/bold] "
            "(or press Enter for a suggested portfolio)",
            default=random.choice(example_scenarios),
        )

        print("Testing Investment Report Generator with New Workflow Structure")
        print("=" * 70)

        result = await investment_workflow.arun(
            input="Generate comprehensive investment analysis and portfolio allocation recommendations",
            companies=companies,
        )

        pprint_run_response(result, markdown=True)

    asyncio.run(main())
