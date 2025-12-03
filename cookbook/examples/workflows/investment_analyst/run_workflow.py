from agents import (
    company_research_agent,
    database_setup_agent,
    esg_analysis_agent,
    financial_analysis_agent,
    investment_recommendation_agent,
    market_analysis_agent,
    report_synthesis_agent,
    risk_assessment_agent,
    valuation_agent,
)
from agno.workflow import Condition, Loop, Parallel, Router, Step, Steps, Workflow
from agno.workflow.types import StepInput, StepOutput
from models import InvestmentAnalysisRequest, InvestmentType, RiskLevel


### Evaluators
def should_run_analysis(analysis_type: str) -> callable:
    """Create conditional evaluator for analysis types"""

    def evaluator(step_input: StepInput) -> bool:
        request_data = step_input.input
        if isinstance(request_data, InvestmentAnalysisRequest):
            return analysis_type in request_data.analyses_requested
        return False

    return evaluator


def is_high_risk_investment(step_input: StepInput) -> bool:
    """Check if this is a high-risk investment requiring additional analysis"""
    request_data = step_input.input
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
    request_data = step_input.input
    if isinstance(request_data, InvestmentAnalysisRequest):
        return (
            request_data.investment_amount
            and request_data.investment_amount > 50_000_000
        )
    return False


def requires_esg_analysis(step_input: StepInput) -> bool:
    """Check if ESG analysis is required"""
    request_data = step_input.input
    if isinstance(request_data, InvestmentAnalysisRequest):
        return "esg_analysis" in request_data.analyses_requested
    return False


def is_multi_company_analysis(step_input: StepInput) -> bool:
    """Check if analyzing multiple companies"""
    request_data = step_input.input
    if isinstance(request_data, InvestmentAnalysisRequest):
        return len(request_data.companies) > 1
    return False


### Routers
def select_valuation_approach(step_input: StepInput) -> Step:
    """Router to select appropriate valuation approach based on investment type"""
    request_data = step_input.input
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
    request_data = step_input.input
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


### Steps
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


investment_analysis_workflow = Workflow(
    name="Enhanced Investment Analysis Workflow",
    description="Comprehensive investment analysis using workflow v2 primitives with Supabase MCP tools",
    steps=[
        database_setup_step,
        company_research_step,
        # Phase 3: Multi-company analysis
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
    response = investment_analysis_workflow.print_response(
        input=request,
        stream=True,
    )
