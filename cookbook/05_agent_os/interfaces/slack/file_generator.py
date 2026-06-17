"""
File Generator Agent
====================

An agent that generates and uploads files to Slack channels.
Supports creating HTML, Markdown, CSV, JSON, and code files on demand.

Key concepts:
  - ``SlackTools`` with ``enable_upload_file=True`` exposes the upload_file tool
  - Agent generates file content based on user requests
  - Files are uploaded directly to the channel using Slack's files_upload_v2 API
  - Slack displays uploaded files with syntax highlighting for code/markup

Slack scopes: chat:write, files:write
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools.slack import SlackTools

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

file_generator = Agent(
    name="File Generator",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        SlackTools(
            enable_upload_file=True,
            enable_send_message=True,
        )
    ],
    instructions=[
        "You are a file generation assistant.",
        "You can create and upload various file types to Slack:",
        "- HTML files: Create valid HTML5 with embedded CSS for styling",
        "- Markdown files: Create well-formatted .md files",
        "- CSV files: Create data tables with headers",
        "- JSON files: Create properly formatted JSON data",
        "- Code files: Create Python, JavaScript, or other code files",
        "",
        "When asked to create a file:",
        "1. Generate the content based on the user's request",
        "2. Use the upload_file tool with the channel ID from the conversation",
        "3. Choose an appropriate filename with the correct extension",
        "4. Optionally include an initial_comment describing the file",
        "",
        "Keep files well-formatted and include comments/documentation where appropriate.",
    ],
    add_datetime_to_context=True,
)

agent_os = AgentOS(
    agents=[file_generator],
    interfaces=[
        Slack(
            agent=file_generator,
            reply_to_mentions_only=True,
        )
    ],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="file_generator:app", reload=True)
