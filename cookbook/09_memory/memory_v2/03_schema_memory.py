"""
Memory V2 Schemas - Constrain What the LLM Can Save
====================================================
This example shows how to use Pydantic schemas to constrain memory fields.
Instead of free-form key-value storage, schemas define exactly what can be saved.

Different from dynamic memory, schema-based memory provides structure and
validation. The LLM can only save fields defined in your schemas.

Key concepts:
- use_default_schemas: Use built-in schemas for common fields
- Custom schemas: Define domain-specific fields with Pydantic

Example prompts to try:
- "I'm Alice Chen, a senior engineer at TechCorp"
- "I work with Python and TypeScript"
- "I prefer concise responses"
"""

import json
from typing import List, Optional

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.memory_v2 import MemoryCompiler
from agno.models.openai import OpenAIChat
from pydantic import BaseModel, ConfigDict, Field
from rich import print_json

# ============================================================================
# Storage Configuration
# ============================================================================
agent_db = SqliteDb(db_file="tmp/schema_memory.db")


# ============================================================================
# Example 1: Default Schemas
# ============================================================================
def example_default_schemas():
    """Use built-in default schemas for profile, policies, knowledge, feedback."""
    print("=" * 60)
    print("Example 1: Default Schemas")
    print("=" * 60)

    memory = MemoryCompiler(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=agent_db,
        use_default_schemas=True,
    )

    agent = Agent(
        name="Schema Agent",
        model=OpenAIChat(id="gpt-4o"),
        db=agent_db,
        memory_compiler=memory,
        update_memory_on_run=True,
        markdown=True,
    )

    user_id = "schema_user"

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


# ============================================================================
# Example 2: Custom Schemas
# ============================================================================
def example_custom_schemas():
    """Define custom schemas for domain-specific memory fields."""
    print("\n" + "=" * 60)
    print("Example 2: Custom Schemas (Healthcare)")
    print("=" * 60)

    # Custom profile schema for healthcare domain
    class HealthcareProfile(BaseModel):
        model_config = ConfigDict(extra="forbid")

        name: Optional[str] = Field(None, description="Patient or provider name")
        role: Optional[str] = Field(None, description="patient/doctor/nurse/admin")
        department: Optional[str] = Field(None, description="Hospital department")
        specialty: Optional[str] = Field(None, description="Medical specialty")

    # Custom policies for healthcare
    class HealthcarePolicies(BaseModel):
        model_config = ConfigDict(extra="forbid")

        communication_style: Optional[str] = Field(
            None, description="formal/empathetic/clinical"
        )
        include_citations: Optional[bool] = Field(
            None, description="Include medical citations"
        )

    # Custom knowledge for healthcare
    class HealthcareKnowledge(BaseModel):
        model_config = ConfigDict(extra="forbid")

        conditions: Optional[List[str]] = Field(None, description="Relevant conditions")
        medications: Optional[List[str]] = Field(
            None, description="Current medications"
        )

    memory = MemoryCompiler(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=agent_db,
        user_profile_schema=HealthcareProfile,
        user_policies_schema=HealthcarePolicies,
        user_knowledge_schema=HealthcareKnowledge,
    )

    agent = Agent(
        name="Healthcare Agent",
        model=OpenAIChat(id="gpt-4o"),
        db=agent_db,
        memory_compiler=memory,
        update_memory_on_run=True,
        markdown=True,
    )

    user_id = "dr_smith"

    agent.print_response(
        "I'm Dr. Sarah Smith, a cardiologist in the Cardiology department. "
        "I prefer formal, citation-backed responses. "
        "I'm currently treating patients with hypertension and heart failure.",
        user_id=user_id,
        stream=True,
    )

    print("\nExtracted memory (custom healthcare schema):")
    profile = memory.get_user_memory_v2(user_id)
    if profile:
        print_json(json.dumps(profile.to_dict()))


# ============================================================================
# Run Examples
# ============================================================================
if __name__ == "__main__":
    example_default_schemas()
    example_custom_schemas()

# ============================================================================
# More Examples
# ============================================================================
"""
When to use schemas:

1. Compliance requirements:
   - Healthcare: HIPAA-compliant fields only
   - Finance: PCI-DSS compliant fields
   - Legal: Audit-friendly structured data

2. Integration needs:
   - CRM sync: Match CRM field structure
   - Analytics: Consistent data for dashboards
   - Export: Predictable JSON structure

3. Quality control:
   - Prevent garbage data
   - Ensure required fields
   - Type validation

Schema tips:

- Use Optional for all fields (LLM may not extract everything)
- Add descriptions for LLM guidance
- Use ConfigDict(extra="forbid") to reject unknown fields
- Keep schemas focused on your domain
"""
