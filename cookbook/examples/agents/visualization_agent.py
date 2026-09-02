"""
Visualization Agent Example

This example demonstrates how to use the VisualizationTools to create
various types of charts and visualizations. The agent can create bar charts,
line charts, pie charts, scatter plots, histograms, and multi-series charts
with advanced features like colors, annotations, and time series support.

Run: `python cookbook/examples/visualization_agent.py`
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.visualization import VisualizationTools

# Create the visualization agent with all chart types
agent = Agent(
    name="Data Visualization Assistant",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[VisualizationTools(output_dir="charts", all=True)],
    instructions=[
        "You are a data visualization expert that helps users create beautiful and informative charts.",
        "Use the appropriate chart type based on the data and user's needs.",
        "For bar charts and line charts, use colors and value labels when appropriate.",
        "For time series data, use the is_timeseries flag to format dates properly.",
        "For multi-series data, use the create_multi_series_chart function.",
        "Always provide the file path to the created chart.",
    ],
    markdown=True,
)

if __name__ == "__main__":
    # Example 1: Simple bar chart
    print("\n" + "=" * 80)
    print("Example 1: Creating a simple bar chart")
    print("=" * 80)
    agent.print_response(
        "Create a bar chart showing quarterly sales: Q1=$45000, Q2=$52000, Q3=$48000, Q4=$61000. "
        "Use colors red, green, blue, and purple. Show values on the bars. "
        "Title it 'Quarterly Sales Performance'."
    )

    # Example 2: Line chart with time series
    print("\n" + "=" * 80)
    print("Example 2: Creating a time series line chart")
    print("=" * 80)
    agent.print_response(
        "Create a line chart showing user growth over time: "
        "2024-01-01=1000, 2024-02-01=1500, 2024-03-01=2200, 2024-04-01=3100, 2024-05-01=4200. "
        "This is time series data. Show values on the points. "
        "Title it 'User Growth Trend'. Use a purple line."
    )

    # Example 3: Multi-series bar chart
    print("\n" + "=" * 80)
    print("Example 3: Creating a multi-series comparison")
    print("=" * 80)
    agent.print_response(
        "Create a grouped bar chart comparing Product A and Product B sales across months. "
        "Product A: Jan=100, Feb=120, Mar=140, Apr=135. "
        "Product B: Jan=90, Feb=110, Mar=150, Apr=145. "
        "Use blue for Product A and orange for Product B. "
        "Title it 'Product Sales Comparison'."
    )

    # Example 4: Pie chart
    print("\n" + "=" * 80)
    print("Example 4: Creating a pie chart")
    print("=" * 80)
    agent.print_response(
        "Create a pie chart showing market share: "
        "Company A=35%, Company B=28%, Company C=22%, Company D=15%. "
        "Title it 'Market Share Distribution'."
    )

    # Example 5: Scatter plot
    print("\n" + "=" * 80)
    print("Example 5: Creating a scatter plot")
    print("=" * 80)
    agent.print_response(
        "Create a scatter plot to show correlation between hours studied and test scores. "
        "Hours: [1, 2, 3, 4, 5, 6, 7, 8]. "
        "Scores: [45, 55, 62, 68, 75, 82, 88, 92]. "
        "Title it 'Study Time vs Test Score'."
    )

    # Example 6: Stacked bar chart
    print("\n" + "=" * 80)
    print("Example 6: Creating a stacked bar chart")
    print("=" * 80)
    agent.print_response(
        "Create a stacked bar chart showing revenue sources by quarter. "
        "Online: Q1=20000, Q2=25000, Q3=28000, Q4=32000. "
        "Retail: Q1=15000, Q2=18000, Q3=17000, Q4=19000. "
        "Use a stacked bar chart type. "
        "Title it 'Revenue by Channel'."
    )

    # Example 7: Histogram
    print("\n" + "=" * 80)
    print("Example 7: Creating a histogram")
    print("=" * 80)
    agent.print_response(
        "Create a histogram showing the distribution of customer ages: "
        "[23, 25, 28, 32, 35, 38, 42, 45, 47, 51, 53, 55, 58, 62, 65, 68, 72]. "
        "Use 5 bins. Title it 'Customer Age Distribution'."
    )

    # Example 8: Line chart with annotations
    print("\n" + "=" * 80)
    print("Example 8: Creating a chart with annotations")
    print("=" * 80)
    agent.print_response(
        "Create a line chart showing website traffic: "
        "Week1=1000, Week2=1200, Week3=2500, Week4=2400, Week5=2800. "
        "Add an annotation at Week 3 saying 'Marketing campaign launched'. "
        "Title it 'Website Traffic Growth'."
    )

    print("\n" + "=" * 80)
    print("All visualizations completed! Check the 'charts' directory.")
    print("=" * 80)
