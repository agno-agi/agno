"""
Organization Memory Example

This example demonstrates how organization-wide context and policies are shared
across all users in an organization.

Key concepts:
- `org_id`: Identifies the organization - all agents with the same org_id share memory
- Org memory is READ-ONLY for agents - admins set it via AgentOS/API
- Two layers: 'context' for domain/product info, 'policies' for rules/constraints

Run this example to see how:
1. Admin sets up organization context (simulating AgentOS)
2. Multiple users benefit from that shared context
3. Organization policies are enforced across all users
"""

from agno.agent import Agent
from agno.db.schemas.org_memory import OrganizationMemory
from agno.db.sqlite import SqliteDb
from agno.memory_v2.memory_compiler import MemoryCompiler
from agno.models.openai import OpenAIChat
from agno.utils.dttm import now_epoch_s
from rich.pretty import pprint

DB_FILE = "tmp/org_memory.db"
ORG_ID = "acme_corp"

db = SqliteDb(db_file=DB_FILE)

# ==============================================================================
# STEP 1: Admin sets up organization memory (via AgentOS/API, not via agent)
# ==============================================================================
print("=" * 60)
print("STEP 1: Admin sets up organization context (via AgentOS)")
print("=" * 60)

# Create organization memory directly - this simulates what AgentOS would do
org_memory = OrganizationMemory(
    org_id=ORG_ID,
    memory_layers={
        "context": {
            "company_name": "Acme Corp",
            "domain": "AI-powered developer tools",
            "main_product": "CodeAssist - an AI code review platform",
            "terminology": {
                "use_terms": ["CodeAssist", "AI-powered", "code review"],
                "avoid_terms": ["magic", "revolutionary"],
            },
        },
        "policies": {
            "brand_voice": "Be helpful, technical but accessible, avoid jargon unless necessary",
            "safety": {
                "competitor_discussions": "Never discuss competitor products or make comparisons",
                "focus": "Focus only on our own capabilities",
            },
        },
    },
    created_at=now_epoch_s(),
)

# Save via MemoryCompiler (simulating AgentOS admin action)
memory_compiler = MemoryCompiler(db=db)
memory_compiler.save_org_memory(org_memory)

print("Organization memory has been set by admin:")
pprint(org_memory.memory_layers)

# ==============================================================================
# STEP 2: Regular user benefits from org context (read-only)
# ==============================================================================
print("\n" + "=" * 60)
print("STEP 2: New employee queries benefit from org context")
print("=" * 60)

user_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    user_id="new_employee",
    org_id=ORG_ID,
    enable_agentic_memory_v2=True,  # For user memory tools
    markdown=True,
)

# Agent can read org context but cannot modify it
user_agent.print_response(
    "I'm a new employee. What does our company do and what should I know about our product?",
    stream=True,
)

# ==============================================================================
# STEP 3: Support rep follows org policies automatically
# ==============================================================================
print("\n" + "=" * 60)
print("STEP 3: Support rep follows org policies automatically")
print("=" * 60)

support_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    user_id="support_rep",
    org_id=ORG_ID,
    enable_agentic_memory_v2=True,
    markdown=True,
)

# Agent should follow the safety policy about competitor discussions
support_agent.print_response(
    "A customer asked how CodeAssist compares to GitHub Copilot. How should I respond?",
    stream=True,
)

# ==============================================================================
# STEP 4: Runtime org_id switching (read-only access)
# ==============================================================================
print("\n" + "=" * 60)
print("STEP 4: Runtime org_id switching")
print("=" * 60)

# Setup a second organization (simulating AgentOS admin action)
SECOND_ORG_ID = "tech_startup"

org_memory_2 = OrganizationMemory(
    org_id=SECOND_ORG_ID,
    memory_layers={
        "context": {
            "company_name": "TechStartup Inc",
            "domain": "B2B SaaS",
            "focus": "Enterprise workflow automation",
        },
        "policies": {
            "communication": "Always be concise and action-oriented",
        },
    },
    created_at=now_epoch_s(),
)
memory_compiler.save_org_memory(org_memory_2)

# Create a single agent that can switch between orgs at runtime
shared_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    enable_agentic_memory_v2=True,
    markdown=True,
)

# Query with first org context
shared_agent.print_response(
    "What company are we and what do we do?",
    user_id="test_user",
    org_id=ORG_ID,  # Acme Corp
    stream=True,
)

# Same agent, switch to second org context
shared_agent.print_response(
    "What company are we and what do we do?",
    user_id="test_user",
    org_id=SECOND_ORG_ID,  # TechStartup Inc
    stream=True,
)

# ==============================================================================
# FINAL: Display org memory states
# ==============================================================================
print("\n" + "=" * 60)
print("FINAL ORG MEMORY STATES")
print("=" * 60)

print("\nAcme Corp org memory:")
acme_memory = memory_compiler.get_org_memory(ORG_ID)
if acme_memory:
    pprint(acme_memory.memory_layers)
else:
    print("No org memory found")

print("\nTech Startup org memory:")
startup_memory = memory_compiler.get_org_memory(SECOND_ORG_ID)
if startup_memory:
    pprint(startup_memory.memory_layers)
else:
    print("No org memory found")
