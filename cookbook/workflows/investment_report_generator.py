"""💰 Investment Report Generator - Your AI Financial Analysis Studio!

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

Run `pip install openai yfinance agno` to install dependencies.
"""

from pathlib import Path
from shutil import rmtree
from textwrap import dedent
from typing import Iterator

from agno.agent import Agent, RunResponse
from agno.storage.sqlite import SqliteStorage
from agno.tools.yfinance import YFinanceTools
from agno.utils.log import logger
from agno.utils.pprint import pprint_run_response
from agno.workflow import Workflow

reports_dir = Path(__file__).parent.joinpath("reports", "investment")
if reports_dir.is_dir():
    rmtree(path=reports_dir, ignore_errors=True)
reports_dir.mkdir(parents=True, exist_ok=True)
stock_analyst_report = str(reports_dir.joinpath("stock_analyst_report.md"))
research_analyst_report = str(reports_dir.joinpath("research_analyst_report.md"))
investment_report = str(reports_dir.joinpath("investment_report.md"))


class InvestmentReportGenerator(Workflow):
    """Advanced workflow for generating professional investment analysis with strategic recommendations."""

    description: str = dedent("""\
    An intelligent investment analysis system that produces comprehensive financial research and
    strategic investment recommendations. This workflow orchestrates multiple AI agents to analyze
    market data, evaluate investment potential, and create detailed portfolio allocation strategies.
    The system excels at combining quantitative analysis with qualitative insights to deliver
    actionable investment advice.
    """)

    stock_analyst: Agent = Agent(
        name="Stock Analyst",
        tools=[
            YFinanceTools(
                company_info=True, analyst_recommendations=True, company_news=True
            )
        ],
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
        1. Market Research 📊
           - Analyze company fundamentals and metrics
           - Review recent market performance
           - Evaluate competitive positioning
           - Assess industry trends and dynamics
        2. Financial Analysis 💹
           - Examine key financial ratios
           - Review analyst recommendations
           - Analyze recent news impact
           - Identify growth catalysts
        3. Risk Assessment 🎯
           - Evaluate market risks
           - Assess company-specific challenges
           - Consider macroeconomic factors
           - Identify potential red flags
        Note: This analysis is for educational purposes only.\
        """),
        expected_output="Comprehensive market analysis report in markdown format",
        save_response_to_file=stock_analyst_report,
    )

    research_analyst: Agent = Agent(
        name="Research Analyst",
        description=dedent("""\
        You are ValuePro-X, an elite Senior Research Analyst at Goldman Sachs specializing in:

        - Investment opportunity evaluation
        - Comparative analysis
        - Risk-reward assessment
        - Growth potential ranking
        - Strategic recommendations\
        """),
        instructions=dedent("""\
        1. Investment Analysis 🔍
           - Evaluate each company's potential
           - Compare relative valuations
           - Assess competitive advantages
           - Consider market positioning
        2. Risk Evaluation 📈
           - Analyze risk factors
           - Consider market conditions
           - Evaluate growth sustainability
           - Assess management capability
        3. Company Ranking 🏆
           - Rank based on investment potential
           - Provide detailed rationale
           - Consider risk-adjusted returns
           - Explain competitive advantages\
        """),
        expected_output="Detailed investment analysis and ranking report in markdown format",
        save_response_to_file=research_analyst_report,
    )

    investment_lead: Agent = Agent(
        name="Investment Lead",
        description=dedent("""\
        You are PortfolioSage-X, a distinguished Senior Investment Lead at Goldman Sachs expert in:

        - Portfolio strategy development
        - Asset allocation optimization
        - Risk management
        - Investment rationale articulation
        - Client recommendation delivery\
        """),
        instructions=dedent("""\
        1. Portfolio Strategy 💼
           - Develop allocation strategy
           - Optimize risk-reward balance
           - Consider diversification
           - Set investment timeframes
        2. Investment Rationale 📝
           - Explain allocation decisions
           - Support with analysis
           - Address potential concerns
           - Highlight growth catalysts
        3. Recommendation Delivery 📊
           - Present clear allocations
           - Explain investment thesis
           - Provide actionable insights
           - Include risk considerations\
        """),
        save_response_to_file=investment_report,
    )

    def run(self, companies: str) -> Iterator[RunResponse]:
        logger.info(f"Getting investment reports for companies: {companies}")
        initial_report: RunResponse = self.stock_analyst.run(companies)
        if initial_report is None or not initial_report.content:
            yield RunResponse(
                run_id=self.run_id,
                content="Sorry, could not get the stock analyst report.",
            )
            return

        logger.info("Ranking companies based on investment potential.")
        ranked_companies: RunResponse = self.research_analyst.run(
            initial_report.content
        )
        if ranked_companies is None or not ranked_companies.content:
            yield RunResponse(
                run_id=self.run_id, content="Sorry, could not get the ranked companies."
            )
            return

        logger.info(
            "Reviewing the research report and producing an investment proposal."
        )
        yield from self.investment_lead.run(ranked_companies.content, stream=True)


# Run the workflow if the script is executed directly
if __name__ == "__main__":
    import random

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
        "(or press Enter for a suggested portfolio)\n✨",
        default=random.choice(example_scenarios),
    )

    # Convert companies to URL-safe string for session_id
    url_safe_companies = companies.lower().replace(" ", "-").replace(",", "")

    # Initialize the investment analyst workflow
    investment_report_generator = InvestmentReportGenerator(
        session_id=f"investment-report-{url_safe_companies}",
        storage=SqliteStorage(
            table_name="investment_report_workflows",
            db_file="tmp/agno_workflows.db",
        ),
    )

    # Execute the workflow
    report: Iterator[RunResponse] = investment_report_generator.run(companies=companies)

    # Print the report
    pprint_run_response(report, markdown=True)
