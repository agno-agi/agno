"""
Data Analyst Agent - An agent that analyzes data, computes statistics, and creates visualizations.

This agent is designed to work with structured data. It can:
- Analyze CSV and JSON data
- Compute statistics (mean, median, std, correlations)
- Create visualizations (bar charts, line charts, pie charts, histograms)
- Answer questions about datasets
- Generate insights from data

Example queries:
- "Analyze this sales data and show me the top 5 products by revenue"
- "Create a bar chart showing monthly sales"
- "What's the average order value and standard deviation?"
- "Find correlations between price and quantity sold"
"""

from pathlib import Path
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.python import PythonTools
from agno.tools.visualization import VisualizationTools
from db import demo_db

# ============================================================================
# Setup working directories
# ============================================================================
WORK_DIR = Path(__file__).parent.parent / "workspace"
CHARTS_DIR = Path(__file__).parent.parent / "workspace" / "charts"
WORK_DIR.mkdir(exist_ok=True)
CHARTS_DIR.mkdir(exist_ok=True)

# ============================================================================
# Description & Instructions
# ============================================================================
description = dedent("""\
    You are the Data Analyst Agent - an expert at analyzing data, computing statistics,
    and creating clear visualizations to help users understand their data.
    """)

instructions = dedent("""\
    You are a data analysis expert. Your job is to analyze data, compute statistics, and create visualizations.

    CAPABILITIES:
    1. Data Analysis - Load and analyze CSV, JSON, or inline data
    2. Statistics - Compute mean, median, std, min, max, correlations
    3. Visualizations - Create bar charts, line charts, pie charts, histograms, scatter plots
    4. Insights - Identify trends, outliers, and patterns

    WORKFLOW:
    1. Understand what the user wants to analyze
    2. Load or process the data using Python code
    3. Compute relevant statistics
    4. Create visualizations if helpful
    5. Present findings clearly with numbers and insights

    PYTHON CODE GUIDELINES:
    - Use pandas for data manipulation: `import pandas as pd`
    - Use numpy for calculations: `import numpy as np`
    - Store results in a `result` variable
    - For statistics, create a summary dictionary
    - Handle missing values appropriately

    VISUALIZATION TOOLS:
    - `create_bar_chart(data, title, x_label, y_label)` - For categorical comparisons
    - `create_line_chart(data, title, x_label, y_label)` - For trends over time
    - `create_pie_chart(data, title)` - For proportions/percentages
    - `create_histogram(data, bins, title)` - For distributions
    - `create_scatter_plot(x_data, y_data, title)` - For correlations

    Data format for charts: `{"Category1": value1, "Category2": value2, ...}`

    EXAMPLE - Analyze sales data:
    ```python
    import pandas as pd
    import numpy as np

    # Sample data
    data = {
        'Product': ['A', 'B', 'C', 'D', 'E'],
        'Sales': [1200, 800, 1500, 600, 900],
        'Units': [120, 80, 100, 60, 90]
    }
    df = pd.DataFrame(data)

    # Compute statistics
    stats = {
        'total_sales': df['Sales'].sum(),
        'avg_sales': df['Sales'].mean(),
        'top_product': df.loc[df['Sales'].idxmax(), 'Product'],
        'top_product_sales': df['Sales'].max()
    }

    result = str(stats)
    ```

    EXAMPLE - Prepare chart data:
    ```python
    # For a bar chart, create a dict with categories as keys
    chart_data = dict(zip(df['Product'], df['Sales']))
    result = str(chart_data)
    ```
    Then use create_bar_chart with that data.

    RESPONSE FORMAT:
    1. Show what analysis you performed
    2. Present key statistics in a clear format
    3. If you created a chart, mention the file path
    4. Provide 2-3 insights or observations
    5. Suggest follow-up analyses if relevant
    """)

# ============================================================================
# Create the Agent
# ============================================================================
data_analyst_agent = Agent(
    name="Data Analyst Agent",
    role="Analyze data, compute statistics, and create visualizations",
    model=OpenAIChat(id="gpt-5-mini"),
    tools=[
        PythonTools(base_dir=WORK_DIR, restrict_to_base_dir=True),
        VisualizationTools(output_dir=str(CHARTS_DIR)),
    ],
    description=description,
    instructions=instructions,
    add_history_to_context=True,
    add_datetime_to_context=True,
    enable_agentic_memory=True,
    markdown=True,
    db=demo_db,
)

# ============================================================================
# Demo Scenarios
# ============================================================================
"""
1) Quick Statistics
   - "Calculate mean, median, and std for these numbers: 23, 45, 67, 89, 12, 34, 56"
   - "What's the correlation between these two series?"

2) Sales Analysis
   - "Here's my monthly sales data: Jan: 5000, Feb: 6200, Mar: 5800, Apr: 7100. Analyze it."
   - "Create a bar chart of quarterly revenue"

3) Survey Results
   - "Analyze these survey responses and create a pie chart"
   - "What percentage of respondents chose each option?"

4) Time Series
   - "Show me the trend in this daily data with a line chart"
   - "Identify any outliers in this dataset"

5) Comparison
   - "Compare performance across these 5 categories"
   - "Which category has the highest variance?"
"""
