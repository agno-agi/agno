"""
E2B Tools Example - Demonstrates how to use the E2B toolkit for sandboxed code execution.

This example shows how to:
1. Set up authentication with E2B API
2. Initialize the E2BTools with proper configuration
3. Create an agent that can run Python code in a secure sandbox
4. Use the sandbox for data analysis, visualization, and more

Prerequisites:
1. Create an account and get your API key from E2B:
   - Visit https://e2b.dev/
   - Sign up for an account
   - Navigate to the Dashboard to get your API key

2. Install required packages:
   pip install e2b_code_interpreter pandas matplotlib

3. Set environment variable:
   export E2B_API_KEY=your_api_key

Features:
- Run Python code in a secure sandbox environment
- Upload and download files to/from the sandbox
- Create and download data visualizations
- Run servers within the sandbox with public URLs
- Manage sandbox lifecycle (timeout, shutdown)
- Access the internet from within the sandbox

Usage:
Run this script with the E2B_API_KEY environment variable set to interact
with the E2B sandbox through natural language commands.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.e2b import E2BTools

# Example 1: Include specific E2B functions for basic code execution
basic_e2b_tools = E2BTools(
    timeout=600,  # 10 minutes timeout (in seconds)
    include_tools=[
        "run_python_code",
        "list_files",
        "read_file_content",
        "write_file_content",
    ],
)

# Example 2: Exclude server-related functions for security
safe_e2b_tools = E2BTools(
    timeout=600, exclude_tools=["run_server", "get_public_url", "run_command"]
)

# Example 3: Full E2B functionality (default)
full_e2b_tools = E2BTools(
    timeout=600,  # 10 minutes timeout (in seconds)
)

# Create agents with different tool configurations
basic_agent = Agent(
    name="Basic Code Execution Sandbox",
    id="e2b-basic-sandbox",
    model=OpenAIChat(id="gpt-4o"),
    tools=[basic_e2b_tools],
    markdown=True,
    instructions=[
        "You are a Python code execution assistant with basic file operations.",
        "You can run Python code and manage files in a secure sandbox.",
    ],
)

agent = Agent(
    name="Full Code Execution Sandbox",
    id="e2b-sandbox",
    model=OpenAIChat(id="gpt-4o"),
    tools=[full_e2b_tools],
    markdown=True,
    instructions=[
        "You are an expert at writing and validating Python code using a secure E2B sandbox environment.",
        "Your primary purpose is to:",
        "1. Write clear, efficient Python code based on user requests",
        "2. Execute and verify the code in the E2B sandbox",
        "3. Share the complete code with the user, as this is the main use case",
        "4. Provide thorough explanations of how the code works",
        "",
        "You can use these tools:",
        "1. Run Python code (run_python_code)",
        "2. Upload files to the sandbox (upload_file)",
        "3. Download files from the sandbox (download_file_from_sandbox)",
        "4. Generate and add visualizations as image artifacts (download_png_result)",
        "5. List files in the sandbox (list_files)",
        "6. Read and write file content (read_file_content, write_file_content)",
        "7. Start web servers and get public URLs (run_server, get_public_url)",
        "8. Manage the sandbox lifecycle (set_sandbox_timeout, get_sandbox_status, shutdown_sandbox)",
        "",
        "Guidelines:",
        "- ALWAYS share the complete code with the user, properly formatted in code blocks",
        "- Verify code functionality by executing it in the sandbox before sharing",
        "- Iterate and debug code as needed to ensure it works correctly",
        "- Use pandas, matplotlib, and other Python libraries for data analysis when appropriate",
        "- Create proper visualizations when requested and add them as image artifacts to show inline",
        "- Handle file uploads and downloads properly",
        "- Explain your approach and the code's functionality in detail",
        "- Format responses with both code and explanations for maximum clarity",
        "- Handle errors gracefully and explain any issues encountered",
    ],
)


agent.print_response(
    "Write Python code to generate the first 10 Fibonacci numbers and calculate their sum and average"
)

# agent.print_response(
#     " upload file cookbook/tools/sample_data.csv and use it to create a matplotlib visualization of total sales by region and provide chart image or its downloaded path or any link  "
# )
# agent.print_response(" use dataset sample_data.csv and create a matplotlib visualization of total sales by region and provide chart image")
# agent.print_response(" run a server and Write a simple fast api web server that displays 'Hello from E2B Sandbox!' and run it , use run_command to get the data from the server and provide the  url of api swagger docs and host link")
# agent.print_response(
#     " run server and Create and run a Python script that fetch top 5 latest news from hackernews using hackernews api"
# )
# agent.print_response("Extend the sandbox timeout to 20 minutes")
# agent.print_response("list all sandboxes ")
