"""
Pandas Tools - Data Analysis and DataFrame Operations

This example demonstrates how to use PandasTools for data manipulation and analysis.
Shows enable_ flag patterns for selective function access.
PandasTools is a small tool (<6 functions) so it uses enable_ flags.

Run: `pip install pandas` to install the dependencies
"""

from agno.agent import Agent
from agno.tools.pandas import PandasTools

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
