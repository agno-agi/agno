"""💰 Investment Report Generator - Your AI Financial Analysis Studio!"""

from textwrap import dedent
from typing import List

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.tools.yfinance import YFinanceTools
from agno.workflow.step import Step
from agno.workflow.types import StepOutput, WorkflowExecutionInput
from agno.workflow.workflow import Workflow
from pydantic import BaseModel

# ************* Database Setup *************
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url, id="agno_assist_db")
# *******************************


# ************* Model Setup *************
class InvestmentWorkflowInput(BaseModel):
    companies: List[str]


# *******************************


# ************* Output Schemas *************
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


# *******************************


# ************* Agents *************
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
    output_schema=PortfolioAllocation,
)
# *******************************


# ************* Execution function *************
async def investment_analysis_execution(
    execution_input: WorkflowExecutionInput,
) -> StepOutput:
    """Execute the complete investment analysis workflow"""

    # Get inputs
    companies: List[str] = execution_input.input

    if not companies:
        return "❌ No company symbols provided"

    print(f"🚀 Starting investment analysis for companies: {companies}")

    # Phase 1: Stock Analysis
    print("\n📊 PHASE 1: COMPREHENSIVE STOCK ANALYSIS")
    print("=" * 60)

    analysis_prompt = f"""

    Please conduct a comprehensive analysis of the following companies: {companies}

    For each company, provide:
    1. Current market position and financial metrics
    2. Recent performance and analyst recommendations
    3. Industry trends and competitive landscape
    4. Risk factors and growth potential
    5. News impact and market sentiment
    Companies to analyze: {companies}
    """

    print("🔍 Analyzing market data and fundamentals...")
    stock_analysis_result = await stock_analyst.arun(analysis_prompt)
    stock_analysis = stock_analysis_result.content

    # Save to file
    stock_analysis_report = f"""
    # Stock Analysis Report\n\n
    **Companies:** {stock_analysis.company_symbols}\n\n
    ## Market Analysis\n{stock_analysis.market_analysis}\n\n
    ## Financial Metrics\n{stock_analysis.financial_metrics}\n\n
    ## Risk Assessment\n{stock_analysis.risk_assessment}\n\n
    ## Recommendations\n{stock_analysis.recommendations}\n
    """

    # Phase 2: Investment Ranking
    print("\n🏆 PHASE 2: INVESTMENT POTENTIAL RANKING")
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

    print("📈 Ranking companies by investment potential...")
    ranking_result = await research_analyst.arun(ranking_prompt)
    ranking_analysis = ranking_result.content

    # Save to file
    ranking_analysis_report = f"""
    # Investment Ranking Report\n\n
    ## Company Rankings\n{ranking_analysis.ranked_companies}\n\n
    ## Investment Rationale\n{ranking_analysis.investment_rationale}\n\n
    ## Risk Evaluation\n{ranking_analysis.risk_evaluation}\n\n
    ## Growth Potential\n{ranking_analysis.growth_potential}\n
    """

    # Phase 3: Portfolio Allocation Strategy
    print("\n💼 PHASE 3: PORTFOLIO ALLOCATION STRATEGY")
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

    print("💰 Developing portfolio allocation strategy...")
    portfolio_result = await investment_lead.arun(portfolio_prompt)
    portfolio_strategy = portfolio_result.content

    # Save to file
    portfolio_strategy_report = f"""
    # Investment Portfolio Report\n\n
    ## Allocation Strategy\n{portfolio_strategy.allocation_strategy}\n\n
    ## Investment Thesis\n{portfolio_strategy.investment_thesis}\n\n
    ## Risk Management\n{portfolio_strategy.risk_management}\n\n
    ## Final Recommendations\n{portfolio_strategy.final_recommendations}\n
    """

    # Final summary
    summary = f""" ### Final Summary ###
    INVESTMENT ANALYSIS WORKFLOW COMPLETED!

    ### Analysis Summary ###
    • Companies Analyzed: {companies}
    • Market Analysis: ✅ Completed
    • Investment Ranking: ✅ Completed
    • Portfolio Strategy: ✅ Completed

    ### Reports Generated ###
    • Stock Analysis: {stock_analysis_report}
    \n
    • Investment Ranking: {ranking_analysis_report}
    \n
    • Portfolio Strategy: {portfolio_strategy_report}

    ### Key Insights ###
    {portfolio_strategy.allocation_strategy[:200]}...

    ### Disclaimer ###
    This analysis is for educational purposes only and should not be considered as financial advice.
    """

    return summary


# *******************************


# ************* Step *************
investment_analysis_step = Step(
    name="Investment Analysis",
    executor=investment_analysis_execution,
)
# *******************************


# ************* Workflow definition *************
investment_workflow = Workflow(
    name="Investment Report Generator",
    description="Automated investment analysis with market research and portfolio allocation",
    db=db,
    steps=[investment_analysis_step],
    input_schema=InvestmentWorkflowInput,
    session_state={},  # Initialize empty workflow session state
)
# *******************************
