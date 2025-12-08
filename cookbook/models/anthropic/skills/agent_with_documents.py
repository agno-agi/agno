"""
Agno Agent with Word Document Skills.

This cookbook demonstrates how to use Claude's docx skill to create Word
documents through Agno agents.

Prerequisites:
- pip install agno anthropic
- export ANTHROPIC_API_KEY="your_api_key_here"
"""

import os

from agno.agent import Agent
from agno.models.anthropic import Claude
from anthropic import Anthropic
from file_download_helper import download_skill_files

# Create a simple agent with Word document skills
document_agent = Agent(
    name="Document Creator",
    model=Claude(
        id="claude-sonnet-4-5-20250929",
        skills=[
            {"type": "anthropic", "skill_id": "docx", "version": "latest"}
        ],  # Enable Word document skill
    ),
    instructions=[
        "You are a professional document writer with access to Word document skills.",
        "Create well-structured documents with clear sections and professional formatting.",
        "Use headings, lists, and tables where appropriate.",
    ],
    markdown=True,
)


if __name__ == "__main__":
    # Check for API key
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise ValueError("ANTHROPIC_API_KEY environment variable not set")

    print("=" * 60)
    print("Agno Agent with Word Document Skills")
    print("=" * 60)

    # Example: Project proposal using the agent
    prompt = (
        "Create a project proposal document for 'Mobile App Development':\n\n"
        "Title: Mobile App Development Proposal\n\n"
        "1. Executive Summary:\n"
        "   Project to build a task management mobile app\n"
        "   Timeline: 12 weeks, Budget: $120K\n\n"
        "2. Project Overview:\n"
        "   - Native iOS and Android app\n"
        "   - Key features: Task lists, reminders, team collaboration\n"
        "   - Target users: Small business teams\n\n"
        "3. Scope of Work:\n"
        "   - Requirements gathering (Week 1-2)\n"
        "   - Design and prototyping (Week 3-4)\n"
        "   - Development (Week 5-10)\n"
        "   - Testing and launch (Week 11-12)\n\n"
        "4. Team:\n"
        "   - 2 developers, 1 designer, 1 project manager\n\n"
        "5. Budget Breakdown:\n"
        "   - Development: $80K\n"
        "   - Design: $25K\n"
        "   - Testing: $10K\n"
        "   - Contingency: $5K\n\n"
        "6. Success Metrics:\n"
        "   - 1000 users in first month\n"
        "   - 4.5+ star rating\n"
        "   - 70% user retention\n\n"
        "Save as 'mobile_app_proposal.docx'"
    )

    print("\nCreating document...\n")

    # Use the agent to create the document
    response = document_agent.run(prompt)

    # Print the agent's response
    print(response.content)

    # Download files created by the agent
    print("\n" + "=" * 60)
    print("Downloading files...")
    print("=" * 60)

    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    # Download files from the agent's response
    if response.messages:
        for msg in response.messages:
            if hasattr(msg, "provider_data") and msg.provider_data:
                files = download_skill_files(
                    msg.provider_data,
                    client,
                    default_filename="mobile_app_proposal.docx",
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
