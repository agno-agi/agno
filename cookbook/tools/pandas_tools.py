"""
Pandas Tools - Data Analysis and DataFrame Operations

This example demonstrates how to use PandasTools for data manipulation and analysis.
Shows enable_ flag patterns for selective function access.
PandasTools is a small tool (<6 functions) so it uses enable_ flags.

Run: `pip install pandas` to install the dependencies
"""

from agno.agent import Agent
from agno.tools.pandas import PandasTools

# Example 1: All functions enabled (default behavior) 
agent_full = Agent(
    tools=[PandasTools()],  # All functions enabled by default
    description="You are a data analyst with full pandas capabilities for comprehensive data analysis.",
    instructions=[
        "Help users with all aspects of pandas data manipulation",
        "Create, modify, analyze, and visualize DataFrames", 
        "Provide detailed explanations of data operations",
        "Suggest best practices for data analysis workflows",
    ],
    markdown=True,
)

# Example 2: Enable specific data manipulation functions
agent_basic = Agent(
    tools=[PandasTools(
        enable_create_dataframe=True,
        enable_read_csv=True,
        enable_basic_operations=True,  # Assuming this function exists
        enable_advanced_analytics=False,  # Disable complex analytics
    )],
    description="You are a basic data handler focused on DataFrame creation and simple operations.",
    instructions=[
        "Create DataFrames from various data sources",
        "Perform basic data operations like filtering and sorting",
        "Focus on data input/output and simple transformations",
        "Keep analysis straightforward and accessible",
    ],
    markdown=True,
)

# Example 3: Enable all functions using 'all=True' pattern
agent_comprehensive = Agent(
    tools=[PandasTools(all=True)],  # Enable all functions explicitly
    description="You are a comprehensive data science assistant with all pandas capabilities.",
    instructions=[
        "Perform advanced data analysis and statistical operations",
        "Handle complex data transformations and aggregations",
        "Provide detailed insights and data visualizations",
        "Support end-to-end data analysis workflows",
    ],
    markdown=True,
)

# Example 4: Read-only data analysis
agent_readonly = Agent(
    tools=[PandasTools(
        enable_create_dataframe=False,   # Disable DataFrame creation
        enable_read_csv=True,
        enable_data_analysis=True,       # Assuming this function exists  
        enable_data_export=False,        # Disable data export
    )],
    description="You are a data analyst focused on analyzing existing datasets without modifications.",
    instructions=[
        "Analyze existing DataFrames and CSV files",
        "Provide insights and statistical summaries", 
        "Cannot create new data or export results",
        "Focus on read-only data exploration",
    ],
    markdown=True,
)

# Example usage with the full-featured agent
print("=== DataFrame Creation and Analysis Example ===")
agent_full.print_response("""
Please perform these tasks:
1. Create a pandas dataframe named 'sales_data' using DataFrame() with this sample data:
   {'date': ['2023-01-01', '2023-01-02', '2023-01-03', '2023-01-04', '2023-01-05'],
    'product': ['Widget A', 'Widget B', 'Widget A', 'Widget C', 'Widget B'],
    'quantity': [10, 15, 8, 12, 20],
    'price': [9.99, 15.99, 9.99, 12.99, 15.99]}
2. Show me the first 5 rows of the sales_data dataframe
3. Calculate the total revenue (quantity * price) for each row
""")

print("\n=== Basic Operations Example ===")
agent_basic.print_response("""
Create a simple DataFrame with employee data and show basic statistics:
{'name': ['Alice', 'Bob', 'Charlie'], 'age': [25, 30, 35], 'salary': [50000, 60000, 70000]}
""")

print("\n=== Comprehensive Analysis Example ===")
agent_comprehensive.print_response("""
Analyze the sales data trends, calculate summary statistics, and provide insights about:
1. Total sales by product
2. Average price trends 
3. Quantity distribution analysis
""", markdown=True)
