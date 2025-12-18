"""
Agno Agent with Excel Skills.

This cookbook demonstrates how to use Claude's xlsx skill to create Excel
spreadsheets through Agno agents.

Prerequisites:
- pip install agno anthropic
- export ANTHROPIC_API_KEY="your_api_key_here"
"""

import os

from agno.agent import Agent
from agno.models.anthropic import Claude
from anthropic import Anthropic
from file_download_helper import download_skill_files

# Create a simple agent with Excel skills
excel_agent = Agent(
    name="Excel Creator",
    model=Claude(
        id="claude-sonnet-4-5-20250929",
        skills=[
            {"type": "anthropic", "skill_id": "xlsx", "version": "latest"}
        ],  # Enable Excel spreadsheet skill
    ),
    instructions=[
        "You are a data analysis specialist with access to Excel skills.",
        "Create professional spreadsheets with well-formatted tables and accurate formulas.",
        "Use charts and visualizations to make data insights clear.",
    ],
    markdown=True,
)


if __name__ == "__main__":
    # Check for API key
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise ValueError("ANTHROPIC_API_KEY environment variable not set")

    print("=" * 60)
    print("Agno Agent with Excel Skills")
    print("=" * 60)

    # Example: Sales dashboard using the agent
    prompt = (
        "Create a sales dashboard for January 2026 with:\n"
        "Sales data for 5 reps:\n"
        "- Alice: 24 deals, $385K revenue, 65% close rate\n"
        "- Bob: 19 deals, $298K revenue, 58% close rate\n"
        "- Carol: 31 deals, $467K revenue, 72% close rate\n"
        "- David: 22 deals, $356K revenue, 61% close rate\n"
        "- Emma: 27 deals, $412K revenue, 68% close rate\n\n"
        "Include:\n"
        "1. Table with all metrics\n"
        "2. Total revenue calculation\n"
        "3. Bar chart showing revenue by rep\n"
        "4. Quota attainment (quota: $350K per rep)\n"
        "5. Conditional formatting (green if above quota, red if below)\n"
        "Save as 'sales_dashboard.xlsx'"
    )

    print("\nCreating spreadsheet...\n")

    # Use the agent to create the spreadsheet
    response = excel_agent.run(prompt)

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
                files = download_skill_files(
                    msg.provider_data, client, default_filename="sales_dashboard.xlsx"
                )
                if files:
                    print(f"\n Successfully downloaded {len(files)} file(s):")
                    for file in files:
                        print(f"   - {file}")
                    break
    else:
        print("\n  No files were downloaded")

    print("\n" + "=" * 60)
    print("Done! Check the current directory for your files.")
    print("=" * 60)
