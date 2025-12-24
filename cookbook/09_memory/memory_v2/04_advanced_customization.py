"""Advanced Customization - Custom extraction instructions for MemoryCompiler.

Demonstrates:
- Creating a custom MemoryCompiler with capture_instructions
- Focusing extraction on engineering-specific information
- Using update_memory_on_run for automatic extraction
"""

import json

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.memory_v2 import MemoryCompiler
from agno.models.openai import OpenAIChat
from rich import print_json


def example_custom_instructions():
    """Customize what the MemoryCompiler extracts using capture_instructions."""
    db = SqliteDb(db_file="tmp/custom_memory.db")

    # Define custom extraction instructions for engineering-focused profiles
    custom_instructions = """
    Focus on capturing engineering-specific information:
    - Profile: name, role, company, years of experience
    - Knowledge: primary programming languages, frameworks, cloud platforms, specializations
    - Policies: communication preferences, code style preferences
    - Feedback: what formats/explanations work well or poorly
    """

    memory = MemoryCompiler(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=db,
        capture_instructions=custom_instructions,
    )

    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        db=db,
        memory_compiler=memory,
        update_memory_on_run=True,
        markdown=True,
    )

    user_id = "dev_marcus"

    agent.print_response(
        "I'm Marcus, a staff engineer at CloudScale with 8 years of experience. "
        "I primarily work with Python and Go, using FastAPI and gRPC frameworks. "
        "We deploy everything on AWS and GCP.",
        user_id=user_id,
        stream=True,
    )

    print("\nExtracted profile:")
    profile = memory.get_user_memory_v2(user_id)
    if profile:
        print_json(json.dumps(profile.to_dict()))


if __name__ == "__main__":
    example_custom_instructions()
