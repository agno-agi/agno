"""Excel Tools - Create and Manipulate Excel Files

This example demonstrates how to use ExcelTools for Excel file operations.
ExcelTools enables AI agents to create workbooks, write data, add formulas,
and work with multiple sheets.

Setup:
    pip install openpyxl

Usage:
    python excel_tools.py
"""

from pathlib import Path

from agno.agent import Agent
from agno.tools.excel import ExcelTools

# Create a working directory for Excel files
work_dir = Path(__file__).parent / "excel_output"
work_dir.mkdir(exist_ok=True)

# Example 1: Basic usage with default tools
# create_workbook, write_data, read_data, add_sheet, list_sheets are enabled
agent = Agent(
    tools=[ExcelTools(base_dir=work_dir)],
    description="You are an Excel assistant that helps create and manage spreadsheets.",
    instructions=[
        "Create Excel files with well-organized data",
        "Use meaningful sheet names",
        "Structure data with headers in the first row",
    ],
    markdown=True,
)

# Example 2: Enable all tools including formulas and formatting
agent_full = Agent(
    tools=[ExcelTools(base_dir=work_dir, all=True)],
    description="You are a full-featured Excel assistant with formatting capabilities.",
    instructions=[
        "Create professional Excel reports with formatting",
        "Use formulas for calculations",
        "Apply bold headers and appropriate formatting",
    ],
    markdown=True,
)

# Example 3: Read-only agent for data analysis
agent_readonly = Agent(
    tools=[
        ExcelTools(
            base_dir=work_dir,
            enable_create_workbook=False,
            enable_write_data=False,
            enable_read_data=True,
            enable_add_sheet=False,
            enable_list_sheets=True,
        )
    ],
    description="You are an Excel reader that analyzes existing spreadsheets.",
    instructions=[
        "Read and analyze data from Excel files",
        "Summarize the contents of spreadsheets",
        "Cannot create or modify files",
    ],
    markdown=True,
)

if __name__ == "__main__":
    # Create a sample spreadsheet
    print("=" * 60)
    print("Example 1: Creating a sales report")
    print("=" * 60)
    agent.print_response(
        "Create an Excel file called 'sales_report.xlsx' with a sheet named 'Q1 Sales'. "
        "Add headers: Product, Units Sold, Price, Revenue. "
        "Then add 3 rows of sample product data.",
        stream=True,
    )

    # Read data back
    print("\n" + "=" * 60)
    print("Example 2: Reading the created file")
    print("=" * 60)
    agent.print_response(
        "Read and summarize the data in sales_report.xlsx",
        stream=True,
    )

    # Create formatted report with formulas
    print("\n" + "=" * 60)
    print("Example 3: Creating formatted report with formulas")
    print("=" * 60)
    agent_full.print_response(
        "Create a budget.xlsx file with columns: Category, Planned, Actual. "
        "Add rows for Rent (1000, 1000), Utilities (200, 180), Food (500, 550). "
        "Add a formula in a Total row to sum each column. "
        "Make the headers bold.",
        stream=True,
    )
