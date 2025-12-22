"""Advanced Customization - Schema overrides and nested categories.

Demonstrates:
1. Custom schema for structured profile extraction hints
2. Nested category organization in memory layers
"""

from dataclasses import dataclass
from typing import List, Optional

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.memory_v2 import MemoryCompiler
from agno.models.openai import OpenAIChat
from rich.pretty import pprint


@dataclass
class EngineerProfile:
    name: str
    role: str
    company: str
    years_experience: int
    primary_languages: List[str]
    frameworks: List[str]
    cloud_platforms: Optional[List[str]] = None


def example_schema_override():
    db = SqliteDb(db_file="tmp/custom_memory.db")

    memory = MemoryCompiler(
        model=OpenAIChat(id="gpt-4o-mini"),
        profile_schema=EngineerProfile,
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
    pprint(memory.get_user_profile(user_id).user_profile)

    memory.delete_user_profile(user_id)


def example_nested_categories():
    db = SqliteDb(db_file="tmp/custom_memory.db")
    memory = MemoryCompiler()
    memory.db = db

    user_id = "dev_nested"

    from agno.db.schemas.user_profile import UserProfile

    user_profile = UserProfile(
        user_id=user_id,
        user_profile={
            "personal": {"name": "Jordan", "location": "Seattle", "timezone": "PST"},
            "professional": {
                "role": "Tech Lead",
                "company": "InnovateTech",
                "team_size": 5,
            },
            "technical": {
                "languages": ["Python", "Rust", "TypeScript"],
                "specialization": "distributed systems",
            },
        },
        memory_layers={
            "policies": {
                "communication": {"style": "direct", "verbosity": "concise"},
                "format": {"code_examples": True, "use_markdown": True},
                "behavior": {"no_emojis": True, "no_buzzwords": True},
            },
            "feedback": {
                "positive": ["step-by-step explanations work well"],
                "negative": ["too much context before the answer"],
            },
        },
    )
    memory.upsert_user_profile(user_profile)

    print("\nCompiled context:")
    print(memory.compile_user_memory(user_id))

    memory.delete_user_profile(user_id)


if __name__ == "__main__":
    example_schema_override()
    example_nested_categories()
