"""
Agno Agent with PowerPoint Skills.

This cookbook demonstrates how to use Claude's pptx skill to create PowerPoint
presentations through Agno agents.

Prerequisites:
- pip install agno anthropic
- export ANTHROPIC_API_KEY="your_api_key_here"
"""

import os

from agno.agent import Agent
from agno.models.anthropic import Claude
from anthropic import Anthropic
from file_download_helper import download_skill_files

# Create a simple agent with PowerPoint skills
powerpoint_agent = Agent(
    name="PowerPoint Creator",
    model=Claude(
        id="claude-sonnet-4-5-20250929",
        skills=[
            {"type": "anthropic", "skill_id": "pptx", "version": "latest"}
        ],  # Enable PowerPoint presentation skill
    ),
    instructions=[
        "You are a professional presentation creator with access to PowerPoint skills.",
        "Create well-structured presentations with clear slides and professional design.",
        "Keep text concise - no more than 6 bullet points per slide.",
    ],
    markdown=True,
)


if __name__ == "__main__":
    # Check for API key
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise ValueError("ANTHROPIC_API_KEY environment variable not set")

    print("=" * 60)
    print("Agno Agent with PowerPoint Skills")
    print("=" * 60)

    # Example: Business presentation using the agent
    prompt = (
        "Create a Q4 business review presentation with 5 slides:\n"
        "1. Title slide: 'Q4 2025 Business Review'\n"
        "2. Key metrics: Revenue $2.5M (↑25% YoY), 850 customers\n"
        "3. Major achievements: Product launch, new markets, team growth\n"
        "4. Challenges: Market competition, customer retention\n"
        "5. Q1 2026 goals: $3M revenue, 1000 customers, new features\n"
        "Save as 'q4_review.pptx'"
    )

    print("\nCreating presentation...\n")

    # Use the agent to create the presentation
    response = powerpoint_agent.run(prompt)

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
                    msg.provider_data, client, default_filename="q4_review.pptx"
                )
                if files:
                    print(f"\n Successfully downloaded {len(files)} file(s):")
                    for file in files:
                        print(f"   - {file}")
                    break
    else:
        print("\n No files were downloaded")

    print("\n" + "=" * 60)
    print("Done! Check the current directory for your files.")
    print("=" * 60)
