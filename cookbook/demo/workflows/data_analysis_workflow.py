"""
Data Analysis Workflow - End-to-end data analysis pipeline.

This workflow processes data through four phases:
1. Data Ingestion - Parse and understand the data
2. Analysis - Compute statistics, find patterns
3. Visualization - Create charts and graphs
4. Report - Generate insights report

Example queries:
- "Analyze this sales data and create a complete report"
- "Process this dataset and visualize the key trends"
- "Analyze: Q1: 25000, Q2: 31000, Q3: 28000, Q4: 35000"
"""

from pathlib import Path
from textwrap import dedent
from typing import Dict, Optional

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.tools.python import PythonTools
from agno.tools.reasoning import ReasoningTools
from agno.tools.visualization import VisualizationTools
from agno.workflow import Step, Workflow
from agno.workflow.step import StepInput, StepOutput
from db import demo_db

# ============================================================================
# Setup working directories
# ============================================================================
WORK_DIR = Path(__file__).parent.parent / "workspace"
CHARTS_DIR = WORK_DIR / "charts"
WORK_DIR.mkdir(exist_ok=True)
CHARTS_DIR.mkdir(exist_ok=True)

# ============================================================================
# Phase 1: Data Ingestion Agent
# ============================================================================
ingestion_agent = Agent(
    name="Data Ingestion Agent",
    role="Parse and understand data inputs",
    model=OpenAIChat(id="gpt-5-mini"),
    tools=[
        PythonTools(base_dir=WORK_DIR, restrict_to_base_dir=True),
        ReasoningTools(add_instructions=True),
    ],
    description=dedent("""\
        You are an expert at parsing and understanding data in various formats.
        You transform raw data into structured, analyzable formats.
        """),
    instructions=dedent("""\
        Your job is to parse and understand the input data.

        INPUT FORMATS YOU HANDLE:
        - Inline data (e.g., "Q1: 25000, Q2: 31000")
        - CSV format
        - JSON format
        - Natural language descriptions of data

        OUTPUT:
        1. Describe what data you received
        2. Parse it into a structured format
        3. Create a Python variable with the clean data
        4. Summarize the data structure

        Example output:
        ## Data Ingestion Summary

        ### Input Type
        Quarterly sales data (inline format)

        ### Parsed Data
        ```python
        data = {
            "Q1": 25000,
            "Q2": 31000,
            "Q3": 28000,
            "Q4": 35000
        }
        ```

        ### Data Structure
        - 4 data points (quarterly)
        - Numeric values (currency)
        - Time series data
        """),
    add_history_to_context=True,
    markdown=True,
    db=demo_db,
)

# ============================================================================
# Phase 2: Analysis Agent
# ============================================================================
analysis_agent = Agent(
    name="Analysis Agent",
    role="Compute statistics and find patterns",
    model=OpenAIChat(id="gpt-5-mini"),
    tools=[
        PythonTools(base_dir=WORK_DIR, restrict_to_base_dir=True),
        ReasoningTools(add_instructions=True),
    ],
    description=dedent("""\
        You are a data analyst who computes statistics, identifies patterns,
        and generates insights from data.
        """),
    instructions=dedent("""\
        Analyze the data and compute relevant statistics.

        COMPUTE:
        - Summary statistics (mean, median, min, max, std)
        - Growth rates / changes
        - Trends and patterns
        - Outliers and anomalies

        USE PYTHON:
        ```python
        import pandas as pd
        import numpy as np

        # Your analysis code here
        ```

        OUTPUT:
        ## Analysis Results

        ### Summary Statistics
        | Metric | Value |
        |--------|-------|
        | Mean   | ...   |
        | Median | ...   |
        | ...    | ...   |

        ### Key Findings
        - Finding 1
        - Finding 2
        - ...

        ### Patterns Identified
        - Pattern 1
        - Pattern 2
        """),
    add_history_to_context=True,
    markdown=True,
    db=demo_db,
)

# ============================================================================
# Phase 3: Visualization Agent
# ============================================================================
visualization_agent = Agent(
    name="Visualization Agent",
    role="Create charts and graphs",
    model=OpenAIChat(id="gpt-5-mini"),
    tools=[
        VisualizationTools(output_dir=str(CHARTS_DIR)),
        ReasoningTools(add_instructions=True),
    ],
    description=dedent("""\
        You create clear, informative visualizations to communicate data insights.
        """),
    instructions=dedent("""\
        Create appropriate visualizations for the data.

        AVAILABLE CHARTS:
        - create_bar_chart(data, title, x_label, y_label)
        - create_line_chart(data, title, x_label, y_label)
        - create_pie_chart(data, title)
        - create_histogram(data, bins, title)
        - create_scatter_plot(x_data, y_data, title)

        DATA FORMAT:
        data = {"Category1": value1, "Category2": value2, ...}

        CHOOSE THE RIGHT CHART:
        - Bar chart: Comparing categories
        - Line chart: Trends over time
        - Pie chart: Proportions of a whole
        - Histogram: Distribution of values
        - Scatter plot: Relationship between variables

        OUTPUT:
        ## Visualizations

        ### Chart 1: [Title]
        [Description of what the chart shows]
        File: [path to saved chart]

        ### Chart 2: [Title]
        ...
        """),
    add_history_to_context=True,
    markdown=True,
    db=demo_db,
)

# ============================================================================
# Phase 4: Report Agent
# ============================================================================
report_agent = Agent(
    name="Report Agent",
    role="Generate insights report",
    model=Claude(id="claude-sonnet-4-5"),
    tools=[ReasoningTools(add_instructions=True)],
    description=dedent("""\
        You synthesize analysis results and visualizations into a clear,
        actionable report.
        """),
    instructions=dedent("""\
        Create a comprehensive report from the analysis.

        REPORT STRUCTURE:

        ## Data Analysis Report

        ### Executive Summary
        - Key finding 1
        - Key finding 2
        - Key finding 3

        ### Data Overview
        - What data was analyzed
        - Time period/scope
        - Data quality notes

        ### Statistical Summary
        - Key metrics
        - Trends identified

        ### Visual Insights
        - What the charts reveal
        - Key patterns

        ### Conclusions
        - Main takeaways
        - Implications

        ### Recommendations
        - Suggested actions
        - Areas for further analysis

        QUALITY STANDARDS:
        - Lead with insights, not just numbers
        - Make recommendations actionable
        - Keep it concise but complete
        """),
    add_history_to_context=True,
    markdown=True,
    db=demo_db,
)


# ============================================================================
# Step Connector Function
# ============================================================================
async def pass_through_step(input: StepInput) -> StepOutput:
    """Pass the accumulated context to the next step."""
    previous_outputs: Optional[Dict[str, StepOutput]] = input.previous_step_outputs

    if not previous_outputs:
        return StepOutput(content=input.message or "", success=True)

    # Combine all previous outputs
    combined = "## Previous Analysis Steps\n\n"
    for step_name, output in previous_outputs.items():
        combined += f"### {step_name}\n{output.content}\n\n"

    return StepOutput(content=combined, success=True)


# ============================================================================
# Create Workflow Steps
# ============================================================================
ingestion_step = Step(
    name="Data Ingestion",
    agent=ingestion_agent,
)

analysis_step = Step(
    name="Statistical Analysis",
    agent=analysis_agent,
)

visualization_step = Step(
    name="Visualization",
    agent=visualization_agent,
)

report_step = Step(
    name="Report Generation",
    agent=report_agent,
)

# ============================================================================
# Create the Workflow
# ============================================================================
data_analysis_workflow = Workflow(
    name="Data Analysis Workflow",
    description=dedent("""\
        An end-to-end data analysis pipeline that:
        1. Ingests and parses data
        2. Computes statistics and finds patterns
        3. Creates visualizations
        4. Generates a comprehensive report
        """),
    steps=[
        ingestion_step,
        analysis_step,
        visualization_step,
        report_step,
    ],
    db=demo_db,
)

# ============================================================================
# Demo Scenarios
# ============================================================================
"""
1) Sales Data
   - "Analyze this sales data: Q1: 25000, Q2: 31000, Q3: 28000, Q4: 35000"
   - "Analyze monthly revenue: Jan 5000, Feb 6200, Mar 5800, Apr 7100, May 8200"

2) Performance Data
   - "Analyze these scores: 78, 85, 92, 88, 76, 95, 82, 90, 87, 84"
   - "Analyze response times: Mon 120ms, Tue 135ms, Wed 115ms, Thu 142ms, Fri 128ms"

3) Survey Results
   - "Analyze: Excellent 45%, Good 30%, Average 15%, Poor 10%"
   - "Analyze satisfaction scores by region: North 4.2, South 3.8, East 4.1, West 4.0"

4) Comparison Data
   - "Compare products: A sold 1200, B sold 800, C sold 1500, D sold 600"
   - "Analyze market share: Company A 35%, Company B 28%, Company C 22%, Others 15%"

5) Time Series
   - "Analyze daily users: Mon 5000, Tue 5200, Wed 4800, Thu 5500, Fri 6000, Sat 4000, Sun 3500"
   - "Analyze weekly growth: Week 1: 100, Week 2: 120, Week 3: 145, Week 4: 170"
"""
