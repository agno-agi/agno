"""Shell Command Agent - AI assistant that can execute shell commands safely

This example demonstrates how to create an AI agent that can execute shell commands
with safety features like blacklisting, timeouts, and working directory management.

Run `pip install openai agno` to install dependencies.
"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.shell import ShellTools

# Create a Shell Agent with safety features
shell_agent = Agent(
    name="Shell Command Assistant",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[
        ShellTools(
            all=True,
            enable_blacklist=True,  # Enable command blacklist for safety
            timeout=30,  # 30 second timeout for commands
        )
    ],
    instructions=dedent("""\
        You are a helpful shell command assistant. 🖥️
        
        Your capabilities:
        - Execute shell commands safely with timeout protection
        - Navigate directories and manage working directory
        - List files and get system information
        - Commands are blocked if they're dangerous (rm -rf, format, etc.)
        
        Guidelines:
        1. Always explain what a command does before running it
        2. Be cautious with destructive operations
        3. Use get_current_directory to know where you are
        4. Use list_files to explore directories
        5. Change directory with change_directory before running commands in specific locations
        6. Check OS info to provide platform-specific commands
        
        Safety features enabled:
        - Dangerous commands are automatically blocked
        - Commands timeout after 30 seconds
        - All operations are logged
        
        Always prioritize user safety and data integrity!\
    """),
    markdown=True,
    debug_mode=True,
)

# Example 1: Get system info
print("=" * 80)
print("Example 1: Getting System Information")
print("=" * 80)
response = shell_agent.run("What operating system am I running? Get the OS details.")
print(response.content)

# Example 2: List files
print("\n\n" + "=" * 80)
print("Example 2: Exploring Directory Structure")
print("=" * 80)
response = shell_agent.run(
    "Show me what files and directories are in the current location. "
    "Then tell me the current working directory path."
)
print(response.content)

# Example 3: Execute a safe command
print("\n\n" + "=" * 80)
print("Example 3: Running a Safe Command")
print("=" * 80)
response = shell_agent.run(
    "Run a command to display the current date and time. "
    "Use the appropriate command for the detected operating system."
)
print(response.content)

# Example 4: Test blacklist protection
print("\n\n" + "=" * 80)
print("Example 4: Testing Safety Features")
print("=" * 80)
response = shell_agent.run(
    "Try to run 'rm -rf /' command and tell me what happens. "
    "Explain why this demonstrates the safety features."
)
print(response.content)

# More example prompts to try:
"""
1. "List all Python files in the current directory"
2. "Check if git is installed on this system"
3. "What is the current disk usage?"
4. "Navigate to the parent directory and list its contents"
5. "Show me the environment variables"
6. "Create a new directory called 'test' and verify it was created"
"""
