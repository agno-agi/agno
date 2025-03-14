"""
E2B Tools Example - Demonstrates how to use the E2B toolkit for sandboxed code execution.

This example shows how to:
1. Set up authentication with E2B API
2. Initialize the E2BTools with proper configuration
3. Create an agent that can run Python code in a secure sandbox
4. Use the sandbox for data analysis, visualization, and more

Prerequisites:
-------------
1. Create an account and get your API key from E2B:
   - Visit https://e2b.dev/
   - Sign up for an account
   - Navigate to the Dashboard to get your API key

2. Install required packages:
   pip install e2b_code_interpreter pandas matplotlib

3. Set environment variable:
   export E2B_API_KEY=your_api_key

Features:
---------
- Run Python code in a secure sandbox environment
- Upload and download files to/from the sandbox
- Create and download data visualizations
- Run servers within the sandbox with public URLs
- Manage sandbox lifecycle (timeout, shutdown)
- Access the internet from within the sandbox

Usage:
------
Run this script with the E2B_API_KEY environment variable set to interact
with the E2B sandbox through natural language commands.
"""

import os
from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.playground import Playground, serve_playground_app
from agno.tools.e2b import E2BTools

# Instead of creating a sample dataset, use the provided one
# def use_sample_dataset():
#     # Path to the provided sample data
#     sample_data_path = Path("cookbook/tools/sample_data.csv")

#     # Make sure the file exists
#     if not sample_data_path.exists():
#         print(f"❌ Sample data file not found at: {sample_data_path}")
#         exit(1)

#     print(f"✅ Using sample dataset at: {sample_data_path}")
#     return sample_data_path

# Get E2B API key from environment
API_KEY = os.getenv("E2B_API_KEY")
if not API_KEY:
    print("⚠️ E2B_API_KEY environment variable not set!")
    print("Please set it with: export E2B_API_KEY=your_api_key")
    print("You can get your API key from: https://e2b.dev/")
    exit(1)

# Initialize E2B tools with configuration
e2b_tools = E2BTools(
    api_key=API_KEY,
    timeout=600,  # 10 minutes timeout (in seconds)
)

# Replace the create_sample_dataset() call with use_sample_dataset()
# dataset_path = use_sample_dataset()
# print(f"✅ Using sample dataset at: {dataset_path}")

# # Upload sample data to the sandbox
# sandbox_file_path = "/Desktop/lab/sample_data/sample_data.csv"  # Use the path that's working
# upload_result = e2b_tools.upload_file(str(dataset_path), sandbox_file_path)
# print(f"📤 Upload result: {upload_result}")

# Create an agent with E2B capabilities
agent = Agent(
    name="Code Execution Sandbox",
    agent_id="e2b-sandbox",
    model=OpenAIChat(id="gpt-4o"),
    tools=[e2b_tools],
    markdown=True,
    show_tool_calls=True,
    instructions=[
        "You are an expert at running Python code in a secure E2B sandbox environment.",
        "You can:",
        "1. Run Python code (run_python_code)",
        "2. Upload files to the sandbox (upload_file)",
        "3. Download files from the sandbox (download_file_from_sandbox)",
        "4. Generate and download visualizations (download_png_result, download_chart_data)",
        "5. List files in the sandbox (list_files)",
        "6. Read and write file content (read_file_content, write_file_content)",
        "7. Start web servers and get public URLs (run_server, get_public_url)",
        "8. Manage the sandbox lifecycle (set_sandbox_timeout, get_sandbox_status, shutdown_sandbox)",
        "",
        "Guidelines:",
        "- Always execute code in the sandbox, never locally",
        "- Use pandas, matplotlib, and other Python libraries for data analysis",
        "- Create proper visualizations when asked",
        "- Handle file uploads and downloads properly",
        "- Provide clear explanations of code and results",
        "- Format code blocks properly",
        "- Handle errors gracefully",
    ],
)

# Example usage - uncomment the ones you want to try
# agent.print_response(
#     "Write Python code to generate the first 10 Fibonacci numbers and calculate their sum and average"
# )

# More examples (uncomment to use):
# agent.print_response("List all files currently in the sandbox")
# agent_response = agent.print_response(
#     "I need you to analyze the CSV file at '/home/user/sample_data.csv' in the sandbox.\n\n"
#     "First, verify the file exists by running Python code to check the current directory and if the file exists.\n\n"
#     "Then analyze the data by:\n"
#     "1. Reading the CSV file\n"
#     "2. Calculating sales (price * quantity) for each record\n"
#     "3. Grouping by customer_region and summing the sales\n"
#     "4. Creating a bar chart showing total sales by region\n\n"
#     "The file is located at: /home/user/sample_data.csv"
# )

# # After the analysis is complete, automatically download the generated PNG
# print("\nAutomatically downloading the generated visualization...")
# download_result = e2b_tools.download_png_result(result_index=0, output_path="total_sales_by_region.png")
# print(f"Download result: {download_result}")
# print(f"Visualization saved to: total_sales_by_region.png")

# Verify file exists and create a matplotlib visualization
# agent.print_response(" upload file cookbook/tools/sample_data.csv and use it to create a matplotlib visualization of total sales by region and provide chart image link url ")
# agent.print_response(" use dataset sample_data.csv and create a matplotlib visualization of total sales by region and provide chart image")

# agent.print_response(" run a server and Write a simple fast api web server that displays 'Hello from E2B Sandbox!' and run it and provide the url of api swagger docs")
# agent.print_response(" run server and Create and run a Python script that featches latest news using duckduckgo search api")
# agent.print_response("Extend the sandbox timeout to 20 minutes")
agent.print_response("shutdown all sandboxes")
# app = Playground(agents=[agent]).get_app()

# if __name__ == "__main__":
#     serve_playground_app("e2b_tools:app", reload=True)
