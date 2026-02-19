"""
Example: Using DatabaseSkills Loader

This example demonstrates how to load skills from a PostgreSQL database
using the DatabaseSkills loader.

Setup:
1. Run the schema.sql script to create the database tables
2. Populate the tables with some skills data
3. Update the DATABASE_CONNECTION_STRING below with your database credentials
"""

import os
from pathlib import Path

# Add the project to the path
project_root = Path(__file__).parent.parent.parent.parent.parent
import sys

sys.path.insert(0, str(project_root))

from agno.skills.loaders.database import DatabaseSkills
from agno.skills.loaders.local import LocalSkills
from agno.skills.skill import Skills

# Database connection string
# Format: postgresql://username:password@host:port/database
DATABASE_CONNECTION_STRING = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/agno_skills",
)


def example_database_skills():
    """Load skills from a PostgreSQL database."""
    print("=== Database Skills Loader Example ===\n")

    # Create a database skill loader
    db_loader = DatabaseSkills(
        conn_str=DATABASE_CONNECTION_STRING,
        table_prefix="",  # Set to "agno_" if your tables are prefixed
        validate=True,
    )

    # Load skills from the database
    try:
        skills = db_loader.load()
        print(f"Loaded {len(skills)} skills from database:\n")

        for skill in skills:
            print(f"  - {skill.name}: {skill.description}")
            if skill.scripts:
                print(f"    Scripts: {', '.join(skill.scripts)}")
            if skill.references:
                print(f"    References: {', '.join(skill.references)}")

        return skills
    except Exception as e:
        print(f"Error loading skills from database: {e}")
        return []


def example_mixed_loaders():
    """Load skills from both database and local filesystem."""
    print("\n=== Mixed Loaders Example (Database + Local) ===\n")

    # Create multiple loaders
    loaders = [
        DatabaseSkills(conn_str=DATABASE_CONNECTION_STRING),
        LocalSkills(path="path/to/local/skills"),  # Your local skills path
    ]

    # Create Skills orchestrator with both loaders
    skills_orchestrator = Skills(loaders=loaders)

    # Get all loaded skills
    all_skills = skills_orchestrator.get_all_skills()
    print(f"Total skills loaded: {len(all_skills)}\n")

    for skill in all_skills:
        print(f"  - {skill.name} (source: {skill.source_path})")

    return skills_orchestrator


def example_query_skill_instructions(skills_orchestrator: Skills, skill_name: str):
    """Get instructions for a specific skill."""
    print(f"\n=== Getting Instructions for '{skill_name}' ===\n")

    # Use the orchestrator's tool to get skill instructions
    result = skills_orchestrator.get_skill_instructions(skill_name)
    print(result)


if __name__ == "__main__":
    print("Database Skills Loader Example\n")
    print("=" * 50)

    # Example 1: Load from database only
    example_database_skills()

    # Example 2: Load from both database and local
    # example_mixed_loaders()
