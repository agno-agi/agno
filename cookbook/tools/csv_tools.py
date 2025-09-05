"""
CSV Tools - Data Analysis and Processing for CSV Files

This example demonstrates how to use CsvTools for CSV file operations.
Shows enable_ flag patterns for selective function access.
CsvTools is a small tool (<6 functions) so it uses enable_ flags.

Run: `pip install pandas` to install the dependencies
"""

from pathlib import Path

import httpx
from agno.agent import Agent
from agno.tools.csv_toolkit import CsvTools

# Download sample data
url = "https://agno-public.s3.amazonaws.com/demo_data/IMDB-Movie-Data.csv"
response = httpx.get(url)

imdb_csv = Path(__file__).parent.joinpath("imdb.csv")
imdb_csv.parent.mkdir(parents=True, exist_ok=True)
imdb_csv.write_bytes(response.content)

# Example 1: All functions enabled (default behavior)
agent_full = Agent(
    tools=[CsvTools(csvs=[imdb_csv])],  # All functions enabled by default
    description="You are a comprehensive CSV data analyst with all processing capabilities.",
    instructions=[
        "Help users with complete CSV data analysis and processing",
        "First always get the list of files",
        "Then check the columns in the file",
        "Run queries and provide detailed analysis",
        "Support all CSV operations and transformations",
    ],
    markdown=True,
)

# Example 2: Enable specific functions for read-only analysis
agent_readonly = Agent(
    tools=[
        CsvTools(
            csvs=[imdb_csv],
            enable_list_csv_files=True,
            enable_get_columns=True,
            enable_query_csv_file=True,
            enable_create_csv=False,  # Disable CSV creation
            enable_modify_csv=False,  # Disable CSV modification
        )
    ],
    description="You are a CSV data analyst focused on reading and analyzing existing data.",
    instructions=[
        "Analyze existing CSV files without modifications",
        "Provide insights and run analytical queries",
        "Cannot create or modify CSV files",
        "Focus on data exploration and reporting",
    ],
    markdown=True,
)

# Example 3: Enable all functions using 'all=True' pattern
agent_comprehensive = Agent(
    tools=[CsvTools(csvs=[imdb_csv], all=True)],
    description="You are a full-featured CSV processing expert with all capabilities.",
    instructions=[
        "Perform comprehensive CSV data operations",
        "Create, modify, analyze, and transform CSV files",
        "Support advanced data processing workflows",
        "Provide end-to-end CSV data management",
    ],
    markdown=True,
)

# Example 4: Query-focused agent
agent_query = Agent(
    tools=[
        CsvTools(
            csvs=[imdb_csv],
            enable_list_csv_files=True,
            enable_get_columns=True,
            enable_query_csv_file=True,
        )
    ],
    description="You are a CSV query specialist focused on data analysis and reporting.",
    instructions=[
        "Execute analytical queries on CSV data",
        "Provide statistical insights and summaries",
        "Generate reports based on data analysis",
        "Focus on extracting valuable insights from datasets",
    ],
    markdown=True,
)

print("=== Full CSV Analysis Example ===")
print("Using comprehensive agent for complete CSV operations")
agent_full.print_response(
    "Analyze the IMDB movie dataset. Show me the top 10 highest-rated movies and their directors.",
    markdown=True,
)

print("\n=== Read-Only Analysis Example ===")
print("Using read-only agent for data exploration")
agent_readonly.print_response(
    "What are the key statistics about the movie ratings and revenue in this dataset?",
    markdown=True,
)

print("\n=== Query-Focused Example ===")
print("Using query specialist for targeted analysis")
agent_query.print_response(
    "Find movies from the year 2016 with ratings above 8.0 and show their genres.",
    markdown=True,
)

# Optional: Interactive CLI mode
# agent_full.cli_app(stream=False)
