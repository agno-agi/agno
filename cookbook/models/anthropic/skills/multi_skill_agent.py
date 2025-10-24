"""
Multi-Skill Agent - PowerPoint, Excel, and Word.

This cookbook demonstrates how to create an agent with multiple Claude Agent Skills
that can create presentations, spreadsheets, and documents in a single workflow.

Prerequisites:
- pip install agno anthropic
- export ANTHROPIC_API_KEY="your_api_key_here"
"""

import os

from agno.agent import Agent
from agno.models.anthropic import Claude
from anthropic import Anthropic
from file_download_helper import download_skill_files

# Create an agent with multiple skills
multi_skill_agent = Agent(
    name="Multi-Skill Document Creator",
    model=Claude(
        id="claude-sonnet-4-5-20250929",
        skills=[
            {"type": "anthropic", "skill_id": "pptx", "version": "latest"},
            {"type": "anthropic", "skill_id": "xlsx", "version": "latest"},
            {"type": "anthropic", "skill_id": "docx", "version": "latest"},
        ],  # Enable PowerPoint, Excel, and Word skills
    ),
    instructions=[
        "You are a comprehensive business document creator.",
        "You have access to PowerPoint, Excel, and Word document skills.",
        "Create professional document packages with consistent information across all files.",
    ],
    markdown=True,
)


if __name__ == "__main__":
    # Check for API key
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise ValueError("ANTHROPIC_API_KEY environment variable not set")

    print("=" * 60)
    print("Multi-Skill Agent - Document Package Creation")
    print("=" * 60)

    # Example: Create a simple multi-skill document package
    prompt = (
        "Create a sales report package with 2 documents:\n\n"
        "1. EXCEL SPREADSHEET (sales_report.xlsx):\n"
        "   - Q4 sales data: Oct $450K, Nov $520K, Dec $610K\n"
        "   - Include a total formula\n"
        "   - Add a simple bar chart\n\n"
        "2. WORD DOCUMENT (sales_summary.docx):\n"
        "   - Brief Q4 sales summary\n"
        "   - Total sales: $1.58M\n"
        "   - Growth trend: Strong December performance\n"
    )

    print("\nCreating document package...\n")

    # Use the agent to create all documents
    response = multi_skill_agent.run(prompt)

    # Print the agent's response
    print(response.content)

    # Download files created by the agent
    print("\n" + "=" * 60)
    print("Downloading files...")
    print("=" * 60)

    # Access the underlying response to get file IDs
    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    # Download files from the agent's response
    if response.messages:
        for msg in response.messages:
            if hasattr(msg, "provider_data") and msg.provider_data:
                files = download_skill_files(msg.provider_data, client)
                if files:
                    print(f"\n Successfully downloaded {len(files)} file(s):")
                    for file in files:
                        print(f"   - {file}")
                    break
    else:
        print("\n  No files were downloaded")

    print("\n" + "=" * 60)
    print("Done! Check the current directory for all files.")
    print("=" * 60)
