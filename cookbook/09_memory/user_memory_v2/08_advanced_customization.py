"""Advanced Customization - Per-layer controls and schema overrides.

Demonstrates:
1. Per-layer extraction controls (enable/disable specific layers)
2. Custom schema for structured profile extraction
3. Custom extraction prompts per layer
4. Nested category organization
"""

from dataclasses import dataclass
from typing import List, Optional

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.memory import MemoryManagerV2
from agno.models.openai import OpenAIChat
from rich.pretty import pprint


# Define a custom schema for user profiles
@dataclass
class EngineerProfile:
    name: str
    role: str
    company: str
    years_experience: int
    primary_languages: List[str]
    frameworks: List[str]
    cloud_platforms: Optional[List[str]] = None


def example_per_layer_controls():
    """Demonstrate enabling/disabling specific memory layers."""
    print("=" * 60)
    print("Example 1: Per-Layer Extraction Controls")
    print("=" * 60)

    db = SqliteDb(db_file="tmp/custom_memory.db")

    # Only extract profile and policies, skip knowledge and feedback
    memory = MemoryManagerV2(
        db=db,
        model=OpenAIChat(id="gpt-4o-mini"),
        update_memory_on_run=True,
        # Per-layer extraction controls
        extract_profile=True,
        extract_policies=True,
        extract_knowledge=False,  # Skip knowledge extraction
        extract_feedback=False,  # Skip feedback extraction
        # Context compilation controls (what gets injected)
        add_user_profile_to_context=True,
        add_user_policies_to_context=True,
        add_knowledge_to_context=False,
        add_feedback_to_context=False,
    )

    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        memory_manager_v2=memory,
        markdown=True,
    )

    user_id = "dev_sarah"

    print("\nUser introduces themselves with project context:")
    agent.print_response(
        "Hi, I'm Sarah, a senior Python developer at DataFlow Inc. "
        "I'm currently working on a data pipeline project using Apache Kafka. "
        "Please be concise in your responses.",
        user_id=user_id,
        stream=True,
    )

    print("\n--- Extracted Memory ---")
    user = memory.get_user(user_id)
    print("\nProfile (extracted):")
    pprint(user.user_profile)
    print("\nPolicies (extracted):")
    pprint(user.policies)
    print("\nKnowledge (should be empty - extraction disabled):")
    pprint(user.knowledge)

    memory.delete_user(user_id)


def example_schema_override():
    """Demonstrate custom schema for structured extraction."""
    print("\n" + "=" * 60)
    print("Example 2: Schema Override for Structured Extraction")
    print("=" * 60)

    db = SqliteDb(db_file="tmp/custom_memory.db")

    # Use custom schema to guide extraction
    memory = MemoryManagerV2(
        db=db,
        model=OpenAIChat(id="gpt-4o-mini"),
        update_memory_on_run=True,
        # Custom schema hints for profile
        profile_schema=EngineerProfile,
    )

    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        memory_manager_v2=memory,
        markdown=True,
    )

    user_id = "dev_marcus"

    print("\nUser shares detailed background:")
    agent.print_response(
        "I'm Marcus, a staff engineer at CloudScale with 8 years of experience. "
        "I primarily work with Python and Go, using FastAPI and gRPC frameworks. "
        "We deploy everything on AWS and GCP.",
        user_id=user_id,
        stream=True,
    )

    print("\n--- Extracted Profile (guided by schema) ---")
    pprint(memory.get_user(user_id).user_profile)

    memory.delete_user(user_id)


def example_custom_extraction_prompt():
    """Demonstrate custom extraction prompts per layer."""
    print("\n" + "=" * 60)
    print("Example 3: Custom Extraction Prompts")
    print("=" * 60)

    db = SqliteDb(db_file="tmp/custom_memory.db")

    # Custom prompt for policies - more restrictive
    custom_policies_prompt = """
Only extract EXPLICIT preference statements. The user must use words like:
- "I want...", "I prefer...", "Always...", "Never...", "Please..."

Do NOT infer preferences from context or behavior.

Examples of what TO save:
- "Please be brief" -> save_user_info("policy", "response_length", "brief")
- "I prefer bullet points" -> save_user_info("policy", "format", "bullet_points")

Examples of what NOT to save:
- User asks a short question -> DON'T assume they want short answers
- User uses formal language -> DON'T assume they prefer formal responses
"""

    memory = MemoryManagerV2(
        db=db,
        model=OpenAIChat(id="gpt-4o-mini"),
        update_memory_on_run=True,
        # Custom prompt for policies layer
        policies_extraction_prompt=custom_policies_prompt,
    )

    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        memory_manager_v2=memory,
        markdown=True,
    )

    user_id = "dev_custom"

    print("\nUser with implicit and explicit preferences:")
    agent.print_response(
        "Hey! I always prefer detailed explanations with code examples. "
        "How do I implement a binary search?",
        user_id=user_id,
        stream=True,
    )

    print("\n--- Extracted Policies (using custom prompt) ---")
    pprint(memory.get_user(user_id).policies)

    memory.delete_user(user_id)


def example_nested_categories():
    """Demonstrate nested category organization in context."""
    print("\n" + "=" * 60)
    print("Example 4: Nested Category Organization")
    print("=" * 60)

    db = SqliteDb(db_file="tmp/custom_memory.db")
    memory = MemoryManagerV2(db=db)

    user_id = "dev_nested"

    # Manually set up nested category structure
    from agno.db.schemas.user_profile import UserProfile

    user = UserProfile(
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
    memory.upsert_user(user)

    print("\n--- Compiled Context (with nested XML tags) ---")
    print(memory.compile_user_context(user_id))

    memory.delete_user(user_id)


if __name__ == "__main__":
    example_per_layer_controls()
    example_schema_override()
    example_custom_extraction_prompt()
    example_nested_categories()
