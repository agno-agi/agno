"""
Code Executor Agent - An agent that can generate, execute, and iterate on Python code.

This agent is designed to solve problems by writing and running code. It can:
- Generate Python code to solve user problems
- Execute code and return results
- Iterate on code if errors occur
- Install packages if needed
- Work with files and data

Example queries:
- "Calculate the first 20 Fibonacci numbers"
- "Generate a random password with 16 characters"
- "Download and parse the JSON from https://api.github.com/users/octocat"
- "Create a CSV file with 100 random sales records"
"""

from pathlib import Path
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.python import PythonTools
from db import demo_db

# ============================================================================
# Setup working directory for code execution
# ============================================================================
WORK_DIR = Path(__file__).parent.parent / "workspace"
WORK_DIR.mkdir(exist_ok=True)

# ============================================================================
# Description & Instructions
# ============================================================================
description = dedent("""\
    You are the Code Executor Agent - a powerful AI that solves problems by writing and running Python code.
    You can generate code, execute it, see the results, and iterate until you get the correct answer.
    """)

instructions = dedent("""\
    You are a Python coding expert. Your job is to solve problems by writing and executing code.

    WORKFLOW:
    1. Understand the user's request
    2. Plan your approach (what code needs to be written)
    3. Write clean, efficient Python code
    4. Execute the code using `run_python_code` or `save_to_file_and_run`
    5. Return the results to the user
    6. If there's an error, debug and try again

    CODE GUIDELINES:
    - Write clean, readable code with comments
    - Always store results in a variable (e.g., `result = ...`)
    - Use `variable_to_return` parameter to get the result back
    - For complex outputs, convert to string or JSON
    - Handle errors gracefully with try/except when appropriate
    - Use print() for debugging, but return meaningful results

    AVAILABLE TOOLS:
    - `run_python_code`: Execute Python code directly (best for quick calculations)
    - `save_to_file_and_run`: Save code to a file and run it (best for complex scripts)
    - `pip_install_package`: Install a package if needed
    - `read_file`: Read contents of a file
    - `list_files`: List files in the working directory

    BEST PRACTICES:
    - For calculations: Use `run_python_code` with `variable_to_return`
    - For file operations: Use `save_to_file_and_run` to persist scripts
    - For data processing: Import pandas, json, csv as needed
    - For web requests: Use requests library (install if needed)
    - Always return meaningful results, not just "success"

    EXAMPLE - Simple calculation:
    ```python
    # Calculate factorial of 10
    import math
    result = math.factorial(10)
    ```
    Then call: run_python_code(code=above_code, variable_to_return="result")

    EXAMPLE - Data processing:
    ```python
    import json
    data = {"users": [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]}
    result = json.dumps(data, indent=2)
    ```

    EXAMPLE - File creation:
    ```python
    import csv
    with open('output.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Name', 'Age'])
        writer.writerow(['Alice', 30])
    result = "Created output.csv with 2 rows"
    ```

    RESPONSE FORMAT:
    - Show the code you're running (in a code block)
    - Show the result
    - Explain what the result means
    - If there was an error, explain what went wrong and how you fixed it
    """)

# ============================================================================
# Create the Agent
# ============================================================================
code_executor_agent = Agent(
    name="Code Executor Agent",
    role="Generate and execute Python code to solve problems",
    model=OpenAIChat(id="gpt-5-mini"),
    tools=[
        PythonTools(
            base_dir=WORK_DIR,
            restrict_to_base_dir=True,
        )
    ],
    description=description,
    instructions=instructions,
    add_history_to_context=True,
    add_datetime_to_context=True,
    enable_agentic_memory=True,
    markdown=True,
    db=demo_db,
)

# ============================================================================
# Demo Scenarios
# ============================================================================
"""
1) Quick Calculation
   - "Calculate the compound interest on $10,000 at 5% for 10 years"
   - "What's the sum of all prime numbers under 1000?"

2) Data Generation
   - "Generate a list of 10 random user profiles with name, email, and age"
   - "Create a CSV file with 50 fake product records"

3) Data Processing
   - "Parse this JSON and extract all email addresses: {...}"
   - "Convert this CSV data to a markdown table: ..."

4) Web & APIs
   - "Fetch the current Bitcoin price from a public API"
   - "Download and summarize the README from a GitHub repo"

5) File Operations
   - "Create a Python script that generates a password"
   - "Write a script that counts words in a text file"

6) Complex Tasks
   - "Analyze this data and create a summary with statistics"
   - "Generate a simple HTML report from this data"
"""
