from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.file_generation import FileGenerationTools
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Step 1: Generate a Report
# ---------------------------------------------------------------------------
report_generator = Agent(
    name="Report Generator",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[FileGenerationTools(enable_pdf_generation=True)],
    instructions=[
        "You are a data analyst that generates reports.",
        "When asked to create a report, use the generate_pdf_file tool to create it.",
        "Include meaningful data in the report.",
    ],
)

generate_report_step = Step(
    name="Generate Report",
    agent=report_generator,
    description="Generate a PDF report with quarterly sales data",
)

# ---------------------------------------------------------------------------
# Step 2: Analyze the Report
# ---------------------------------------------------------------------------
report_analyzer = Agent(
    name="Report Analyzer",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "You are a business analyst.",
        "Analyze the attached PDF report and provide insights.",
        "Focus on trends, anomalies, and recommendations.",
    ],
)

analyze_report_step = Step(
    name="Analyze Report",
    agent=report_analyzer,
    description="Analyze the generated report and provide insights",
)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
report_workflow = Workflow(
    name="Report Generation and Analysis",
    description="Generate a report and analyze it for insights",
    db=SqliteDb(
        session_table="file_propagation_workflow",
        db_file="tmp/file_propagation_workflow.db",
    ),
    steps=[generate_report_step, analyze_report_step],
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("File Generation and Propagation Workflow")
    print("=" * 60)
    print()
    print("This workflow demonstrates file propagation between steps:")
    print("1. Step 1 generates a PDF report using FileGenerationTools")
    print("2. The file is automatically propagated to Step 2")
    print("3. Step 2 analyzes the report content")
    print()
    print("-" * 60)

    result = report_workflow.run(
        input="Create a quarterly sales report for Q4 2024 with data for 4 regions (North, South, East, West) and then analyze it for insights.",
    )

    print()
    print("=" * 60)
    print("Workflow Result")
    print("=" * 60)
    print()
    print(result.content)
    print()

    # Show file propagation
    print("-" * 60)
    print("Files in workflow output:")
    if result.files:
        for f in result.files:
            print(f"  - {f.filename} ({f.mime_type}, {f.size} bytes)")
    else:
        print("  No files in final output (files were consumed by analysis step)")
