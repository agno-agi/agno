from agents import (
    alternative_suppliers_agent,
    company_overview_agent,
    cost_drivers_agent,
    kraljic_agent,
    pestle_agent,
    porter_agent,
    report_compiler_agent,
    switching_barriers_agent,
)
from agno.workflow import Condition, Parallel, Step, Workflow
from agno.workflow.types import StepInput
from models import ProcurementAnalysisRequest


def should_run_analysis(analysis_type: str) -> callable:
    def evaluator(step_input: StepInput) -> bool:
        request_data = step_input.input
        if isinstance(request_data, ProcurementAnalysisRequest):
            return analysis_type in request_data.analyses_requested
        return False

    return evaluator


company_overview_step = Step(
    name="Company Overview",
    agent=company_overview_agent,
    description="Research and analyze the target company",
)

switching_barriers_step = Step(
    name="Switching Barriers Analysis",
    agent=switching_barriers_agent,
    description="Analyze supplier switching barriers and costs",
)

pestle_step = Step(
    name="PESTLE Analysis",
    agent=pestle_agent,
    description="Conduct PESTLE analysis for procurement strategy",
)

porter_step = Step(
    name="Porter's Five Forces Analysis",
    agent=porter_agent,
    description="Analyze competitive forces in the supply market",
)

kraljic_step = Step(
    name="Kraljic Matrix Analysis",
    agent=kraljic_agent,
    description="Position category on Kraljic Matrix",
)

cost_drivers_step = Step(
    name="Cost Drivers Analysis",
    agent=cost_drivers_agent,
    description="Analyze cost structure and volatility",
)

alternative_suppliers_step = Step(
    name="Alternative Suppliers Research",
    agent=alternative_suppliers_agent,
    description="Identify and evaluate alternative suppliers",
)

report_compilation_step = Step(
    name="Report Compilation",
    agent=report_compiler_agent,
    description="Compile comprehensive procurement analysis report",
)

procurement_workflow = Workflow(
    name="Procurement Analysis Workflow",
    description="Comprehensive procurement intelligence using multiple strategic frameworks",
    steps=[
        company_overview_step,
        Parallel(
            Condition(
                evaluator=should_run_analysis("switching_barriers"),
                steps=[switching_barriers_step],
                name="Switching Barriers Condition",
            ),
            Condition(
                evaluator=should_run_analysis("pestle"),
                steps=[pestle_step],
                name="PESTLE Condition",
            ),
            Condition(
                evaluator=should_run_analysis("porter"),
                steps=[porter_step],
                name="Porter's Five Forces Condition",
            ),
            Condition(
                evaluator=should_run_analysis("kraljic"),
                steps=[kraljic_step],
                name="Kraljic Matrix Condition",
            ),
            Condition(
                evaluator=should_run_analysis("cost_drivers"),
                steps=[cost_drivers_step],
                name="Cost Drivers Condition",
            ),
            Condition(
                evaluator=should_run_analysis("alternative_suppliers"),
                steps=[alternative_suppliers_step],
                name="Alternative Suppliers Condition",
            ),
            name="Analysis Phase",
        ),
        report_compilation_step,
    ],
)

if __name__ == "__main__":
    analysis_details = ProcurementAnalysisRequest(
        companies=["Tesla", "Ford"],
        category_name="Electric Vehicle Components",
        analyses_requested=[
            # "switching_barriers",
            "pestle",
            "porter",
            # "kraljic",
            # "cost_drivers",
            # "alternative_suppliers",
        ],
        region="Global",
        annual_spend=50,
        incumbent_suppliers=["CATL", "Panasonic", "LG Energy Solution"],
    )
    procurement_workflow.print_response(
        input=analysis_details,
        stream=True,
    )
