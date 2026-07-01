"""Data Visualization Tools - Create Charts and Graphs with AI Agents

This example shows how to use the VisualizationTools to create various types of charts
and graphs for data visualization. Demonstrates include_tools/exclude_tools patterns
for selective visualization function access.

Run: `uv pip install matplotlib` to install the dependencies
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.visualization import VisualizationTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


# Example 1: Enable all visualization functions
viz_agent_all = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        VisualizationTools(
            all=True,  # Enable all visualization functions
            output_dir="business_charts",
        )
    ],
    instructions=[
        "You are a data visualization expert with access to all chart types.",
        "Use appropriate visualization functions for the data presented.",
        "Always provide meaningful titles, axis labels, and context.",
        "Suggest insights based on the data visualized.",
        "Format data appropriately for each chart type.",
    ],
    markdown=True,
)

# Example 1b: All visualization functions available (explicit flags)
viz_agent_full = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        VisualizationTools(
            enable_create_bar_chart=True,
            enable_create_line_chart=True,
            enable_create_scatter_plot=True,
            enable_create_pie_chart=True,
            enable_create_histogram=True,
            enable_create_multi_line_chart=True,
            output_dir="business_charts",
        )
    ],
    instructions=[
        "You are a data visualization expert with access to all chart types.",
        "Use appropriate visualization functions for the data presented.",
        "Always provide meaningful titles, axis labels, and context.",
        "Suggest insights based on the data visualized.",
        "Format data appropriately for each chart type.",
    ],
    markdown=True,
)

# Example 2: Enable only basic chart types
viz_agent_basic = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        VisualizationTools(
            enable_create_bar_chart=True,
            enable_create_line_chart=True,
            enable_create_pie_chart=True,
            enable_create_scatter_plot=False,
            enable_create_histogram=False,
            output_dir="basic_charts",
        )
    ],
    instructions=[
        "You are a data visualization specialist focused on basic chart types.",
        "Use bar charts for categorical comparisons.",
        "Use line charts for trends over time.",
        "Use pie charts for part-to-whole relationships.",
        "Keep visualizations simple and clear.",
    ],
    markdown=True,
)

# Example 3: Enable standard visualization functions (avoid complex ones)
viz_agent_safe = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        VisualizationTools(
            enable_create_bar_chart=True,
            enable_create_line_chart=True,
            enable_create_scatter_plot=True,
            enable_create_pie_chart=True,
            enable_create_histogram=True,
            # Note: Complex functions like create_3d_plot, create_heatmap would be False
            output_dir="safe_charts",
        )
    ],
    instructions=[
        "You are a business analyst creating straightforward visualizations.",
        "Focus on clear, easy-to-interpret charts.",
        "Avoid overly complex visualization types.",
        "Ensure charts are suitable for business presentations.",
    ],
    markdown=True,
)

# Example 4: Statistical analysis focused agent
viz_agent_stats = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        VisualizationTools(
            enable_create_scatter_plot=True,
            enable_create_histogram=True,
            enable_create_bar_chart=False,
            enable_create_line_chart=False,
            enable_create_pie_chart=False,
            # Note: Would also enable box_plot, violin_plot if available
            output_dir="stats_charts",
        )
    ],
    instructions=[
        "You are a statistical analyst focused on data distribution and correlation.",
        "Use scatter plots to show relationships between variables.",
        "Use histograms to show data distributions.",
        "Provide statistical insights based on the visualizations.",
    ],
    markdown=True,
)

# Use the all-enabled agent for the main examples
viz_agent = viz_agent_all

# Example 1: Sales Performance Analysis

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Example 1: Creating a Sales Performance Chart")
    viz_agent.print_response(
        """
    Create a bar chart showing our Q4 sales performance:
    - December: $45,000
    - November: $38,000  
    - October: $42,000
    - September: $35,000

    Title it "Q4 Sales Performance" and provide insights about the trend.
    """,
        stream=True,
    )

    print("\n" + "=" * 60 + "\n")

    # Example 2: Market Share Analysis
    print("Example 2: Market Share Pie Chart")
    viz_agent.print_response(
        """
    Create a pie chart showing our market share compared to competitors:
    - Our Company: 35%
    - Competitor A: 25%
    - Competitor B: 20%
    - Competitor C: 15%
    - Others: 5%

    Title it "Market Share Analysis 2024" and analyze our position.
    """,
        stream=True,
    )

    print("\n" + "=" * 60 + "\n")

    # Example 3: Growth Trend Analysis
    print("Example 3: Revenue Growth Trend")
    viz_agent.print_response(
        """
    Create a line chart showing our monthly revenue growth over the past 6 months:
    - January: $120,000
    - February: $135,000
    - March: $128,000
    - April: $145,000
    - May: $158,000
    - June: $162,000

    Title it "Monthly Revenue Growth" and identify trends and growth rate.
    """,
        stream=True,
    )

    print("\n" + "=" * 60 + "\n")

    # Example 4: Advanced Data Analysis
    print("Example 4: Customer Satisfaction vs Sales Correlation")
    viz_agent.print_response(
        """
    Create a scatter plot to analyze the relationship between customer satisfaction scores and sales:

    Customer satisfaction scores (x-axis): [7.2, 8.1, 6.9, 8.5, 7.8, 9.1, 6.5, 8.3, 7.6, 8.9, 7.1, 8.7]
    Sales in thousands (y-axis): [45, 62, 38, 71, 53, 85, 32, 68, 48, 79, 41, 75]

    Title it "Customer Satisfaction vs Sales Performance" and analyze the correlation.
    """,
        stream=True,
    )

    print("\n" + "=" * 60 + "\n")

    # Example 5: Distribution Analysis
    print("Example 5: Score Distribution Histogram")
    viz_agent.print_response(
        """
    Create a histogram showing the distribution of customer review scores:
    Data: [4.1, 4.5, 3.8, 4.7, 4.2, 4.9, 3.9, 4.6, 4.3, 4.8, 4.0, 4.4, 3.7, 4.5, 4.1, 4.6, 4.2, 4.7, 3.9, 4.3]

    Use 6 bins, title it "Customer Review Score Distribution" and analyze the distribution pattern.
    """,
        stream=True,
    )

    print("\n" + "=" * 60 + "\n")

    # Example 6: Multi-Line Chart - Comparing Multiple Series
    print("Example 6: Multi-Line Chart - Revenue vs Expenses Over Time")
    viz_agent.print_response(
        """
    Create a multi-line chart comparing our revenue and expenses over the past 6 months:

    Revenue: Jan: $120,000, Feb: $135,000, Mar: $128,000, Apr: $145,000, May: $158,000, Jun: $162,000
    Expenses: Jan: $95,000, Feb: $98,000, Mar: $102,000, Apr: $108,000, May: $110,000, Jun: $115,000
    Profit: Jan: $25,000, Feb: $37,000, Mar: $26,000, Apr: $37,000, May: $48,000, Jun: $47,000

    Title it "Revenue vs Expenses vs Profit Trend" and analyze the financial health.
    """,
        stream=True,
    )

    print("\n" + "=" * 60 + "\n")

    # Example 7: Multi-Line Chart - Product Comparison
    print("Example 7: Multi-Line Chart - Product Performance Comparison")
    viz_agent.print_response(
        """
    Create a multi-line chart comparing monthly sales for three product lines:

    Product A: Q1: 150, Q2: 180, Q3: 210, Q4: 250
    Product B: Q1: 200, Q2: 190, Q3: 220, Q4: 230
    Product C: Q1: 80, Q2: 120, Q3: 160, Q4: 200

    Title it "Quarterly Product Sales Comparison" with x-axis "Quarter" and y-axis "Units Sold".
    Identify which product is growing fastest.
    """,
        stream=True,
    )

    print(
        "\nAll examples completed. Check the 'business_charts' folder for generated visualizations."
    )

    # More advanced example with business context
    print("\n" + "=" * 60)
    print("ADVANCED EXAMPLE: Business Intelligence Dashboard")
    print("=" * 60 + "\n")

    bi_agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[
            VisualizationTools(
                all=True,  # Enable all visualization functions
                output_dir="dashboard_charts",
            )
        ],
        instructions=[
            "You are a Business Intelligence analyst.",
            "Create comprehensive visualizations for executive dashboards.",
            "Provide actionable insights and recommendations.",
            "Use appropriate chart types for different data scenarios.",
            "Always explain what the data reveals about business performance.",
        ],
        markdown=True,
    )

    # Multi-chart business analysis
    bi_agent.print_response(
        """
    I need to create a comprehensive quarterly business review. Please help me with these visualizations:

    1. First, create a bar chart showing revenue by product line:
       - Software Licenses: $2.3M
       - Support Services: $1.8M
       - Consulting: $1.2M
       - Training: $0.7M

    2. Then create a line chart showing our customer acquisition over the past 12 months:
       - Jan: 45, Feb: 52, Mar: 48, Apr: 61, May: 58, Jun: 67
       - Jul: 73, Aug: 69, Sep: 78, Oct: 84, Nov: 81, Dec: 89

    3. Create a multi-line chart comparing website traffic sources over the past 6 months:
       - Organic Search: Jan: 12000, Feb: 13500, Mar: 14200, Apr: 15800, May: 16500, Jun: 17200
       - Paid Ads: Jan: 8000, Feb: 8500, Mar: 9200, Apr: 9800, May: 10100, Jun: 10500
       - Social Media: Jan: 3000, Feb: 3800, Mar: 4500, Apr: 5200, May: 6100, Jun: 7000

    4. Finally, create a pie chart showing our expense breakdown:
       - Personnel: 45%
       - Technology: 25%
       - Marketing: 15%
       - Operations: 10%
       - Other: 5%

    For each chart, provide business insights and recommendations for next quarter.
    """,
        stream=True,
    )
