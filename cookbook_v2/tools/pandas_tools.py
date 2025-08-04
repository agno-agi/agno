from agno.agent import Agent
from agno.tools.pandas import PandasTools

# Create an agent with PandasTools
agent = Agent(tools=[PandasTools()])

# Example: Create a dataframe with sample data and get the first 5 rows
agent.print_response("""
Please perform these tasks:
1. Create a pandas dataframe named 'sales_data' using DataFrame() with this sample data:
   {'date': ['2023-01-01', '2023-01-02', '2023-01-03', '2023-01-04', '2023-01-05'],
    'product': ['Widget A', 'Widget B', 'Widget A', 'Widget C', 'Widget B'],
    'quantity': [10, 15, 8, 12, 20],
    'price': [9.99, 15.99, 9.99, 12.99, 15.99]}
2. Show me the first 5 rows of the sales_data dataframe
""")
