from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.memory_v2 import MemoryCompiler
from agno.models.openai import OpenAIChat
from rich.pretty import pprint


def example_custom_instructions():
    """Customize what the MemoryCompiler extracts using profile_capture_instructions."""
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
        profile_capture_instructions=custom_instructions,
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
    profile = memory.get_user_profile(user_id)
    if profile:
        pprint(profile.to_dict())

    memory.delete_user_profile(user_id)


def example_nested_categories():
    """Manually create a profile with nested category organization."""
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
    memory.save_user_profile(user_profile)

    print("\nCompiled context:")
    print(memory.compile_user_profile(user_id))

    memory.delete_user_profile(user_id)


if __name__ == "__main__":
    example_custom_instructions()
    example_nested_categories()
