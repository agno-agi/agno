"""Schema-Based Memory V2 - Constrain what the LLM can save using Pydantic schemas.

Demonstrates:
- Using default schemas with use_default_schemas=True
- Defining custom schemas to limit what fields the LLM can save
- Schema validation ensures structured, predictable memory storage
"""

import json
from typing import List, Optional

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.memory_v2 import MemoryCompiler
from agno.models.openai import OpenAIChat
from pydantic import BaseModel, ConfigDict, Field
from rich import print_json

DB_FILE = "tmp/schema_memory.db"


def example_default_schemas():
    """Use built-in default schemas for profile, policies, knowledge, feedback."""
    print("=" * 60)
    print("EXAMPLE 1: Default Schemas")
    print("=" * 60)

    db = SqliteDb(db_file=DB_FILE)

    memory = MemoryCompiler(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=db,
        use_default_schemas=True,
    )

    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        db=db,
        memory_compiler=memory,
        update_memory_on_run=True,
        markdown=True,
    )

    user_id = "schema_user"

    # The LLM will extract and save only schema-defined fields
    agent.print_response(
        "Hi, I'm Alice Chen, a senior engineer at TechCorp in San Francisco. "
        "I work with Python and TypeScript. I prefer concise responses with code examples.",
        user_id=user_id,
        stream=True,
    )

    print("\nExtracted memory (schema-constrained):")
    profile = memory.get_user_memory_v2(user_id)
    if profile:
        print_json(json.dumps(profile.to_dict()))


def example_custom_schemas():
    """Define custom schemas for domain-specific memory fields."""
    print("\n" + "=" * 60)
    print("EXAMPLE 2: Custom Schemas")
    print("=" * 60)

    db = SqliteDb(db_file=DB_FILE)

    # Custom profile schema for healthcare domain
    class HealthcareProfile(BaseModel):
        model_config = ConfigDict(extra="forbid")

        name: Optional[str] = Field(None, description="Patient or provider name")
        role: Optional[str] = Field(None, description="patient/doctor/nurse/admin")
        department: Optional[str] = Field(None, description="Hospital department")
        specialty: Optional[str] = Field(None, description="Medical specialty")
        license_number: Optional[str] = Field(None, description="Medical license ID")

    # Custom policies for healthcare
    class HealthcarePolicies(BaseModel):
        model_config = ConfigDict(extra="forbid")

        communication_style: Optional[str] = Field(
            None, description="formal/empathetic/clinical"
        )
        include_citations: Optional[bool] = Field(
            None, description="Include medical citations"
        )
        privacy_level: Optional[str] = Field(None, description="standard/hipaa-strict")

    # Custom knowledge for healthcare
    class HealthcareKnowledge(BaseModel):
        model_config = ConfigDict(extra="forbid")

        conditions: Optional[List[str]] = Field(None, description="Relevant conditions")
        medications: Optional[List[str]] = Field(
            None, description="Current medications"
        )
        allergies: Optional[List[str]] = Field(None, description="Known allergies")

    memory = MemoryCompiler(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=db,
        profile_schema=HealthcareProfile,
        policies_schema=HealthcarePolicies,
        knowledge_schema=HealthcareKnowledge,
    )

    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        db=db,
        memory_compiler=memory,
        update_memory_on_run=True,
        markdown=True,
    )

    user_id = "dr_smith"

    agent.print_response(
        "I'm Dr. Sarah Smith, a cardiologist in the Cardiology department. "
        "License number CA-12345. I prefer formal, citation-backed responses. "
        "I'm currently treating patients with hypertension and heart failure. "
        "Many of my patients are on ACE inhibitors and beta blockers.",
        user_id=user_id,
        stream=True,
    )

    print("\nExtracted memory (custom healthcare schema):")
    profile = memory.get_user_memory_v2(user_id)
    if profile:
        print_json(json.dumps(profile.to_dict()))


def example_agentic_with_schemas():
    """Agentic memory with schema constraints - user explicitly manages memory."""
    print("\n" + "=" * 60)
    print("EXAMPLE 3: Agentic Memory with Schemas")
    print("=" * 60)

    db = SqliteDb(db_file=DB_FILE)

    memory = MemoryCompiler(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=db,
        use_default_schemas=True,
    )

    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        db=db,
        memory_compiler=memory,
        enable_agentic_memory_v2=True,  # User explicitly manages memory
        markdown=True,
    )

    user_id = "agentic_user"

    # User explicitly asks to save information
    agent.print_response(
        "Remember that I'm working on a machine learning project using PyTorch and transformers.",
        user_id=user_id,
        stream=True,
    )

    agent.print_response(
        "Update my preferences: I want detailed responses with code examples.",
        user_id=user_id,
        stream=True,
    )

    print("\nFinal memory state:")
    profile = memory.get_user_memory_v2(user_id)
    if profile:
        print_json(json.dumps(profile.to_dict()))


if __name__ == "__main__":
    example_default_schemas()
    example_custom_schemas()
    example_agentic_with_schemas()
