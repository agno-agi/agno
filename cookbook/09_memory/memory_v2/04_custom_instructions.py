"""
Memory V2 Customization - Custom Extraction Instructions
=========================================================
This example shows how to customize what the MemoryCompiler extracts.
Use per-layer instructions to focus extraction on domain-specific information.

Different from default extraction, custom instructions tell the MemoryCompiler
exactly what types of information to capture for your use case.

Key concepts:
- MemoryCompiler: Configures how memory is extracted and stored
- user_capture_instructions: Global guidance for extraction
- Per-layer instructions: user_profile_instructions, user_knowledge_instructions, etc.

Example prompts to try:
- "I'm a staff engineer with 8 years of experience"
- "I work with Python, Go, FastAPI, and gRPC"
- "I prefer concise responses with type hints"
"""

import json

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.memory_v2 import MemoryCompiler
from agno.models.openai import OpenAIChat
from rich import print_json

# ============================================================================
# Storage Configuration
# ============================================================================
agent_db = SqliteDb(db_file="tmp/custom_memory.db")

# ============================================================================
# Memory Compiler Configuration
# ============================================================================
memory_compiler = MemoryCompiler(
    model=OpenAIChat(id="gpt-4o-mini"),
    db=agent_db,
    # Global extraction guidance
    user_capture_instructions="Focus on engineering-specific information.",
    # Per-layer instructions
    user_profile_instructions="name, role, company, years of experience",
    user_knowledge_instructions="programming languages, frameworks, cloud platforms",
    user_policies_instructions="communication style, code preferences",
)

# ============================================================================
# User Configuration
# ============================================================================
user_id = "dev_marcus"

# ============================================================================
# Create the Agent
# ============================================================================
agent = Agent(
    name="Engineering Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=agent_db,
    memory_compiler=memory_compiler,
    update_memory_on_run=True,
    markdown=True,
)

# ============================================================================
# Run the Agent
# ============================================================================
if __name__ == "__main__":
    agent.print_response(
        "I'm Marcus, a staff engineer at CloudScale with 8 years of experience. "
        "I primarily work with Python and Go, using FastAPI and gRPC frameworks. "
        "We deploy everything on AWS and GCP.",
        user_id=user_id,
        stream=True,
    )

    agent.print_response(
        "I prefer concise responses with production-ready code examples. "
        "Always include error handling and type hints.",
        user_id=user_id,
        stream=True,
    )

    # View extracted profile
    print("\n" + "=" * 60)
    print("Extracted Profile")
    print("=" * 60)

    profile = memory_compiler.get_user_memory_v2(user_id)
    if profile:
        print_json(json.dumps(profile.to_dict()))

# ============================================================================
# More Examples
# ============================================================================
"""
Per-layer instruction examples:

Engineering:
- user_profile_instructions: "name, role, company, years of experience"
- user_knowledge_instructions: "languages, frameworks, cloud platforms"

Healthcare:
- user_profile_instructions: "name, role, department, specialty"
- user_knowledge_instructions: "conditions, medications, allergies"

Sales:
- user_profile_instructions: "name, title, territory, quota"
- user_knowledge_instructions: "accounts, deals, competitors"

The MemoryCompiler uses these instructions to focus extraction
on what matters for your specific domain.
"""
