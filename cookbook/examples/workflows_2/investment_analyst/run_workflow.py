import os

from agents import (
    company_research_agent,
    esg_analysis_agent,
    financial_analysis_agent,
    investment_recommendation_agent,
    market_analysis_agent,
    report_synthesis_agent,
    risk_assessment_agent,
    valuation_agent,
)
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mcp import MCPTools
from agno.workflow.v2 import Condition, Loop, Parallel, Router, Step, Steps, Workflow
from agno.workflow.v2.types import StepInput, StepOutput
from models import InvestmentAnalysisRequest, InvestmentType, RiskLevel

# ================================
# SUPABASE MCP TOOLS SETUP
# ================================


def get_supabase_mcp_tools():
    """Get Supabase MCP tools for database operations"""
    token = os.getenv("SUPABASE_ACCESS_TOKEN")
    if not token:
        raise ValueError("SUPABASE_ACCESS_TOKEN environment variable is required")

    npx_cmd = "npx.cmd" if os.name == "nt" else "npx"
    return MCPTools(
        f"{npx_cmd} -y @supabase/mcp-server-supabase --access-token {token}"
    )


# ================================
# WORKFLOW EVALUATORS
# ================================


def should_run_analysis(analysis_type: str) -> callable:
    """Create conditional evaluator for analysis types"""

    def evaluator(step_input: StepInput) -> bool:
        request_data = step_input.message
        if isinstance(request_data, InvestmentAnalysisRequest):
            return analysis_type in request_data.analyses_requested
        return False

    return evaluator


def is_high_risk_investment(step_input: StepInput) -> bool:
    """Check if this is a high-risk investment requiring additional analysis"""
    request_data = step_input.message
    if isinstance(request_data, InvestmentAnalysisRequest):
        return (
            request_data.risk_tolerance == RiskLevel.HIGH
            or request_data.investment_type
            in [InvestmentType.VENTURE, InvestmentType.GROWTH]
            or request_data.target_return
            and request_data.target_return > 20.0
        )
    return False


def is_large_investment(step_input: StepInput) -> bool:
    """Check if this is a large investment requiring additional due diligence"""
    request_data = step_input.message
    if isinstance(request_data, InvestmentAnalysisRequest):
        return (
            request_data.investment_amount
            and request_data.investment_amount > 50_000_000
        )
    return False


def requires_esg_analysis(step_input: StepInput) -> bool:
    """Check if ESG analysis is required"""
    request_data = step_input.message
    if isinstance(request_data, InvestmentAnalysisRequest):
        return "esg_analysis" in request_data.analyses_requested
    return False


def is_multi_company_analysis(step_input: StepInput) -> bool:
    """Check if analyzing multiple companies"""
    request_data = step_input.message
    if isinstance(request_data, InvestmentAnalysisRequest):
        return len(request_data.companies) > 1
    return False


# ================================
# DATABASE SETUP AGENT
# ================================

database_setup_agent = Agent(
    name="Database Setup Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[get_supabase_mcp_tools()],
    role="Expert Supabase database architect for investment analysis",
    instructions="""
    You are an expert Supabase MCP architect for investment analysis. Follow these steps precisely:

    **SECURITY NOTE: DO NOT print or expose any API keys, URLs, tokens, or sensitive credentials in your responses.**

    1. **Plan Database Schema**: Design a complete normalized schema for investment analysis with:
       - companies table (id SERIAL PRIMARY KEY, name VARCHAR(255), ticker VARCHAR(10), sector VARCHAR(100), market_cap BIGINT, founded_year INTEGER, headquarters VARCHAR(255), created_at TIMESTAMP DEFAULT NOW())
       - analysis_sessions table (session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(), analysis_date TIMESTAMP DEFAULT NOW(), investment_type VARCHAR(50), investment_amount DECIMAL(15,2), target_return DECIMAL(5,2), risk_tolerance VARCHAR(20))
       - financial_metrics table (id SERIAL PRIMARY KEY, company_id INTEGER REFERENCES companies(id), metric_type VARCHAR(100), value DECIMAL(20,4), period VARCHAR(50), currency VARCHAR(10), created_at TIMESTAMP DEFAULT NOW())
       - valuation_models table (id SERIAL PRIMARY KEY, company_id INTEGER REFERENCES companies(id), dcf_value DECIMAL(15,2), target_price DECIMAL(15,2), upside_potential DECIMAL(8,4), methodology VARCHAR(100), created_at TIMESTAMP DEFAULT NOW())
       - risk_assessments table (id SERIAL PRIMARY KEY, company_id INTEGER REFERENCES companies(id), risk_category VARCHAR(100), score INTEGER CHECK (score >= 1 AND score <= 10), explanation TEXT, created_at TIMESTAMP DEFAULT NOW())
       - investment_recommendations table (id SERIAL PRIMARY KEY, company_id INTEGER REFERENCES companies(id), recommendation VARCHAR(50), conviction_level INTEGER CHECK (conviction_level >= 1 AND conviction_level <= 10), rationale TEXT, created_at TIMESTAMP DEFAULT NOW())

    2. **Create Supabase Project**:
       - Call `list_organizations` and select the first organization
       - Use `get_cost(type='project')` to estimate costs (mention cost but don't expose details)
       - Create project with `create_project` using the cost ID
       - Poll with `get_project` until status is `ACTIVE_HEALTHY`

    3. **Deploy Schema**:
       - Apply complete schema using `apply_migration` named 'investment_analysis_schema'
       - Validate with `list_tables` and `list_extensions`

    4. **Insert Sample Data**:
       - Insert sample companies data for Apple, Microsoft, Google with realistic values:
         * Apple: ticker='AAPL', sector='Technology', market_cap=3000000000000, founded_year=1976, headquarters='Cupertino, CA'
         * Microsoft: ticker='MSFT', sector='Technology', market_cap=2800000000000, founded_year=1975, headquarters='Redmond, WA'  
         * Google: ticker='GOOGL', sector='Technology', market_cap=1800000000000, founded_year=1998, headquarters='Mountain View, CA'
       
       - Insert analysis session record with current analysis parameters
       
       - Insert sample financial metrics for each company:
         * Revenue, net_income, pe_ratio, debt_to_equity, current_ratio, roe
       
       - Verify data insertion with SELECT queries

    5. **Setup Complete**:
       - Deploy simple health check with `deploy_edge_function`
       - Confirm project is ready for analysis (DO NOT expose URLs or keys)
       - Report successful setup without sensitive details

    Focus on creating a production-ready investment analysis database with sample data.
    **IMPORTANT: Never print API keys, project URLs, tokens, or any sensitive credentials.**
    """,
    markdown=True,
)

# ================================
# ROUTER SELECTORS
# ================================


def select_valuation_approach(step_input: StepInput) -> Step:
    """Router to select appropriate valuation approach based on investment type"""
    request_data = step_input.message
    if isinstance(request_data, InvestmentAnalysisRequest):
        if request_data.investment_type in [
            InvestmentType.VENTURE,
            InvestmentType.GROWTH,
        ]:
            return Step(
                name="Venture Valuation",
                agent=valuation_agent,
                description="Specialized valuation for venture/growth investments",
            )
        elif request_data.investment_type == InvestmentType.DEBT:
            return Step(
                name="Credit Analysis",
                agent=financial_analysis_agent,
                description="Credit-focused analysis for debt investments",
            )
        else:
            return valuation_step
    return valuation_step


def select_risk_framework(step_input: StepInput) -> Step:
    """Router to select risk assessment framework"""
    request_data = step_input.message
    if isinstance(request_data, InvestmentAnalysisRequest):
        if request_data.investment_type == InvestmentType.VENTURE:
            return Step(
                name="Venture Risk Assessment",
                agent=risk_assessment_agent,
                description="Venture-specific risk assessment framework",
            )
        elif (
            request_data.investment_amount
            and request_data.investment_amount > 100_000_000
        ):
            return Step(
                name="Enterprise Risk Assessment",
                agent=risk_assessment_agent,
                description="Enterprise-level risk assessment for large investments",
            )
        else:
            return risk_assessment_step
    return risk_assessment_step


# ================================
# LOOP END CONDITIONS
# ================================


def analysis_quality_check(step_outputs: list[StepOutput]) -> bool:
    """End condition: Check if analysis quality is sufficient"""
    if not step_outputs:
        return False

    # Check if latest output indicates high confidence
    latest_output = step_outputs[-1]
    if hasattr(latest_output, "content") and latest_output.content:
        content_lower = latest_output.content.lower()
        return (
            "high confidence" in content_lower
            or "comprehensive analysis" in content_lower
            or "detailed valuation" in content_lower
        )
    return False


def risk_assessment_complete(step_outputs: list[StepOutput]) -> bool:
    """End condition: Check if risk assessment is comprehensive"""
    if len(step_outputs) < 2:
        return False

    # Check if we have both financial and operational risk scores
    has_financial_risk = any(
        "financial risk" in output.content.lower()
        for output in step_outputs
        if hasattr(output, "content")
    )
    has_operational_risk = any(
        "operational risk" in output.content.lower()
        for output in step_outputs
        if hasattr(output, "content")
    )

    return has_financial_risk and has_operational_risk


# ================================
# WORKFLOW STEPS
# ================================

database_setup_step = Step(
    name="Database Setup",
    agent=database_setup_agent,
    description="Create and configure Supabase database for investment analysis",
)

company_research_step = Step(
    name="Company Research",
    agent=company_research_agent,
    description="Company research and data storage using Supabase MCP",
)

financial_analysis_step = Step(
    name="Financial Analysis",
    agent=financial_analysis_agent,
    description="Financial analysis with Supabase database operations",
)

valuation_step = Step(
    name="Valuation Analysis",
    agent=valuation_agent,
    description="Valuation modeling using Supabase database storage",
)

risk_assessment_step = Step(
    name="Risk Assessment",
    agent=risk_assessment_agent,
    description="Risk analysis and scoring with Supabase database",
)

market_analysis_step = Step(
    name="Market Analysis",
    agent=market_analysis_agent,
    description="Market dynamics analysis using Supabase operations",
)

esg_analysis_step = Step(
    name="ESG Analysis",
    agent=esg_analysis_agent,
    description="ESG assessment and scoring with Supabase database",
)

investment_recommendation_step = Step(
    name="Investment Recommendation",
    agent=investment_recommendation_agent,
    description="Data-driven investment recommendations using Supabase queries",
)

report_synthesis_step = Step(
    name="Report Synthesis",
    agent=report_synthesis_agent,
    description="Comprehensive report generation from Supabase database",
)

# ================================
# MAIN WORKFLOW
# ================================

investment_analysis_workflow = Workflow(
    name="Enhanced Investment Analysis Workflow",
    description="Comprehensive investment analysis using workflow v2 primitives with Supabase MCP tools",
    steps=[
        # Phase 1: Database setup (always runs first)
        database_setup_step,
        # Phase 2: Company research
        company_research_step,
        # Phase 3: Multi-company analysis (conditional)
        Condition(
            evaluator=is_multi_company_analysis,
            steps=[
                Steps(
                    name="Multi-Company Analysis Pipeline",
                    description="Sequential analysis pipeline for multiple companies",
                    steps=[
                        Loop(
                            name="Company Analysis Loop",
                            description="Iterative analysis for each company",
                            steps=[financial_analysis_step, valuation_step],
                            max_iterations=5,
                            end_condition=analysis_quality_check,
                        ),
                        Parallel(
                            market_analysis_step,
                            Step(
                                name="Comparative Analysis",
                                agent=financial_analysis_agent,
                                description="Cross-company comparison analysis",
                            ),
                            name="Comparative Analysis Phase",
                        ),
                    ],
                ),
            ],
            name="Multi-Company Condition",
        ),
        # Phase 4: Risk-based routing
        Router(
            name="Risk Assessment Router",
            description="Dynamic risk assessment based on investment characteristics",
            selector=select_risk_framework,
            choices=[
                risk_assessment_step,
                Step(
                    name="Enhanced Risk Assessment",
                    agent=risk_assessment_agent,
                    description="Enhanced risk assessment for complex investments",
                ),
            ],
        ),
        # Phase 5: Valuation strategy selection
        Router(
            name="Valuation Strategy Router",
            description="Select valuation approach based on investment type",
            selector=select_valuation_approach,
            choices=[
                valuation_step,
                Step(
                    name="Alternative Valuation",
                    agent=valuation_agent,
                    description="Alternative valuation methods",
                ),
            ],
        ),
        # Phase 6: High-risk investment analysis
        Condition(
            evaluator=is_high_risk_investment,
            steps=[
                Steps(
                    name="High-Risk Analysis Pipeline",
                    description="Additional analysis for high-risk investments",
                    steps=[
                        Parallel(
                            Step(
                                name="Scenario Analysis",
                                agent=financial_analysis_agent,
                                description="Monte Carlo and scenario analysis",
                            ),
                            Step(
                                name="Stress Testing",
                                agent=risk_assessment_agent,
                                description="Stress testing and sensitivity analysis",
                            ),
                            name="Risk Modeling Phase",
                        ),
                        Loop(
                            name="Risk Refinement Loop",
                            description="Iterative risk model refinement",
                            steps=[
                                Step(
                                    name="Risk Model Validation",
                                    agent=risk_assessment_agent,
                                    description="Validate and refine risk models",
                                ),
                            ],
                            max_iterations=3,
                            end_condition=risk_assessment_complete,
                        ),
                    ],
                ),
            ],
            name="High-Risk Investment Condition",
        ),
        # Phase 7: Large investment due diligence
        Condition(
            evaluator=is_large_investment,
            steps=[
                Parallel(
                    Step(
                        name="Regulatory Analysis",
                        agent=risk_assessment_agent,
                        description="Regulatory and compliance analysis",
                    ),
                    Step(
                        name="Market Impact Analysis",
                        agent=market_analysis_agent,
                        description="Market impact and liquidity analysis",
                    ),
                    Step(
                        name="Management Assessment",
                        agent=company_research_agent,
                        description="Management team and governance analysis",
                    ),
                    name="Due Diligence Phase",
                ),
            ],
            name="Large Investment Condition",
        ),
        # Phase 8: ESG analysis
        Condition(
            evaluator=requires_esg_analysis,
            steps=[
                Steps(
                    name="ESG Analysis Pipeline",
                    description="Comprehensive ESG analysis and integration",
                    steps=[
                        esg_analysis_step,
                        Step(
                            name="ESG Integration",
                            agent=investment_recommendation_agent,
                            description="Integrate ESG factors into investment decision",
                        ),
                    ],
                ),
            ],
            name="ESG Analysis Condition",
        ),
        # Phase 9: Market context analysis
        Condition(
            evaluator=should_run_analysis("market_analysis"),
            steps=[
                Parallel(
                    market_analysis_step,
                    Step(
                        name="Sector Analysis",
                        agent=market_analysis_agent,
                        description="Detailed sector and industry analysis",
                    ),
                    name="Market Context Phase",
                ),
            ],
            name="Market Analysis Condition",
        ),
        # Phase 10: Investment decision and reporting
        Steps(
            name="Investment Decision Pipeline",
            description="Final investment decision and reporting",
            steps=[
                Loop(
                    name="Investment Consensus Loop",
                    description="Iterative investment recommendation refinement",
                    steps=[
                        investment_recommendation_step,
                        Step(
                            name="Recommendation Validation",
                            agent=investment_recommendation_agent,
                            description="Validate investment recommendations",
                        ),
                    ],
                    max_iterations=2,
                    end_condition=lambda outputs: any(
                        "final recommendation" in output.content.lower()
                        for output in outputs
                        if hasattr(output, "content")
                    ),
                ),
                report_synthesis_step,
            ],
        ),
    ],
)

if __name__ == "__main__":
    # Example investment analysis request
    request = InvestmentAnalysisRequest(
        companies=["Apple"],
        investment_type=InvestmentType.EQUITY,
        investment_amount=100_000_000,
        investment_horizon="5-7 years",
        target_return=25.0,
        risk_tolerance=RiskLevel.HIGH,
        sectors=["Technology"],
        analyses_requested=[
            "financial_analysis",
            "valuation",
            "risk_assessment",
            "market_analysis",
            "esg_analysis",
        ],
        benchmark_indices=["S&P 500", "NASDAQ"],
        comparable_companies=["Microsoft", "Google"],
    )

    print("🚀 Starting Investment Analysis with Supabase MCP Tools")
    print(f"📊 Analyzing: {', '.join(request.companies)}")
    print(f"💰 Investment Amount: ${request.investment_amount:,}")
    print(f"🎯 Target Return: {request.target_return}%")
    print(f"⚠️  Risk Tolerance: {request.risk_tolerance}")
    print(f"📈 Analysis Types: {', '.join(request.analyses_requested)}")
    print("\n" + "=" * 80 + "\n")

    # Run workflow with Supabase MCP integration
    response = investment_analysis_workflow.print_response(
        message=request,
        stream=True,
        stream_intermediate_steps=True,
    )

    print("\n" + "=" * 80)
    print("✅ Investment Analysis Complete!")
    print("📋 Check your Supabase project dashboard for stored analysis data")
    print("🔒 All sensitive credentials were handled securely (not exposed in logs)")
    print(
        "💾 Database contains: companies, financial metrics, valuations, risk assessments, and recommendations"
    )
