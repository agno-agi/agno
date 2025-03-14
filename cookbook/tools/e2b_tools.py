from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.e2b import E2BTools

e2b_tools = E2BTools(
    timeout=600,  # 10 minutes timeout (in seconds)
)

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


agent.print_response(
    "Write Python code to generate the first 10 Fibonacci numbers and calculate their sum and average"
)

# agent.print_response(" upload file cookbook/tools/sample_data.csv and use it to create a matplotlib visualization of total sales by region and provide chart image link url ")
# agent.print_response(" use dataset sample_data.csv and create a matplotlib visualization of total sales by region and provide chart image")
# agent.print_response(" run a server and Write a simple fast api web server that displays 'Hello from E2B Sandbox!' and run it and provide the url of api swagger docs")
# agent.print_response(
#     " run server and Create and run a Python script that fetch top 5 latest news from hackernews using hackernews api"
# )
# agent.print_response("Extend the sandbox timeout to 20 minutes")
# agent.print_response("list all sandboxes ")
