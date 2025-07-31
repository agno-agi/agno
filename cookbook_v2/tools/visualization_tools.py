"""📊 Data Visualization Tools - Create Charts and Graphs with AI Agents

This example shows how to use the VisualizationTools to create various types of charts
and graphs for data visualization. Perfect for business reports, analytics dashboards,
and data presentations.

Run: `pip install matplotlib` to install the dependencies
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.visualization import VisualizationTools

# Create an agent with visualization capabilities
viz_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[VisualizationTools(output_dir="business_charts")],
    instructions=[
        "You are a data visualization expert and business analyst.",
        "When asked to create charts, use the visualization tools available.",
        "Always provide meaningful titles, axis labels, and context.",
        "Suggest insights based on the data visualized.",
        "Format data appropriately for each chart type.",
    ],
    show_tool_calls=True,
    markdown=True,
)

# Example 1: Sales Performance Analysis
print("📊 Example 1: Creating a Sales Performance Chart")
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
print("🥧 Example 2: Market Share Pie Chart")
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
print("📈 Example 3: Revenue Growth Trend")
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
print("🔹 Example 4: Customer Satisfaction vs Sales Correlation")
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
print("📊 Example 5: Score Distribution Histogram")
viz_agent.print_response(
    """
Create a histogram showing the distribution of customer review scores:
Data: [4.1, 4.5, 3.8, 4.7, 4.2, 4.9, 3.9, 4.6, 4.3, 4.8, 4.0, 4.4, 3.7, 4.5, 4.1, 4.6, 4.2, 4.7, 3.9, 4.3]

Use 6 bins, title it "Customer Review Score Distribution" and analyze the distribution pattern.
""",
    stream=True,
)

print(
    "\n🎯 All examples completed! Check the 'business_charts' folder for generated visualizations."
)

# More advanced example with business context
print("\n" + "=" * 60)
print("🚀 ADVANCED EXAMPLE: Business Intelligence Dashboard")
print("=" * 60 + "\n")

bi_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[VisualizationTools(output_dir="dashboard_charts", enable_all=True)],
    instructions=[
        "You are a Business Intelligence analyst.",
        "Create comprehensive visualizations for executive dashboards.",
        "Provide actionable insights and recommendations.",
        "Use appropriate chart types for different data scenarios.",
        "Always explain what the data reveals about business performance.",
    ],
    show_tool_calls=True,
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

3. Finally, create a pie chart showing our expense breakdown:
   - Personnel: 45%
   - Technology: 25%
   - Marketing: 15%
   - Operations: 10%
   - Other: 5%

For each chart, provide business insights and recommendations for next quarter.
""",
    stream=True,
)
