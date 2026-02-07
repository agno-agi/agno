"""
Scout Agent
===========

Enterprise knowledge agent with Claude Code-like capabilities:
- Awareness: knows what sources exist and what they contain
- Search: grep-like search across sources
- Read: full documents with context (not chunks)
- Write: create and update docs
- Learn: builds knowledge over time

Test:
    python -m agents.scout.agent
"""

from os import getenv

from agno.agent import Agent
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import (
    LearnedKnowledgeConfig,
    LearningMachine,
    LearningMode,
    UserMemoryConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIResponses
from agno.tools.mcp import MCPTools
from agno.tools.reasoning import ReasoningTools
from agno.vectordb.pgvector import PgVector, SearchType
from db import db_url, get_postgres_db

from .context.intent_routing import INTENT_ROUTING_CONTEXT
from .context.source_registry import SOURCE_REGISTRY_STR
from .tools import (
    S3Tools,
    create_get_metadata_tool,
    create_list_sources_tool,
    create_save_intent_discovery_tool,
)

# ============================================================================
# Database & Knowledge
# ============================================================================

agent_db = get_postgres_db()

# KNOWLEDGE: Static, curated (source registry, intent routing, known patterns)
scout_knowledge = Knowledge(
    name="Scout Knowledge",
    vector_db=PgVector(
        db_url=db_url,
        table_name="scout_knowledge",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    contents_db=get_postgres_db(contents_table="scout_knowledge_contents"),
)

# LEARNINGS: Dynamic, discovered (decision traces, what worked, what didn't)
scout_learnings = Knowledge(
    name="Scout Learnings",
    vector_db=PgVector(
        db_url=db_url,
        table_name="scout_learnings",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    contents_db=get_postgres_db(contents_table="scout_learnings_contents"),
)

# ============================================================================
# Tools
# ============================================================================

list_sources = create_list_sources_tool()
get_metadata = create_get_metadata_tool()
save_intent_discovery = create_save_intent_discovery_tool(scout_knowledge)

base_tools: list = [
    # Primary connector (S3)
    S3Tools(),
    # Awareness tools
    list_sources,
    get_metadata,
    # Learning tools
    save_intent_discovery,
    # External search
    MCPTools(
        url=f"https://mcp.exa.ai/mcp?exaApiKey={getenv('EXA_API_KEY', '')}&tools=web_search_exa"
    ),
]

# ============================================================================
# Instructions
# ============================================================================

INSTRUCTIONS = f"""\
You are Scout, an enterprise knowledge agent that finds information across company S3 storage.

## Your Approach

You work like Claude Code, but for enterprise knowledge:
- **Awareness**: You know what sources exist and what they contain
- **Search**: Grep-like search across file contents, not just names
- **Read**: Full documents with context, never chunks
- **Learn**: You remember what works and what doesn't

Your goal: find information fast by knowing where to look.

## Two Knowledge Systems

**Knowledge** (static, curated):
- Source registry: what exists and where
- Intent routing: which source for which question
- Searched automatically before each response

**Learnings** (dynamic, discovered):
- Decision traces: what you searched, what worked, what didn't
- Use `search_learnings` to recall past successes
- Use `save_learning` to remember new patterns

## The Learning Loop

```
1. Search knowledge + learnings (Do I already know where this is?)
2. Navigate: list_sources -> get_metadata -> search -> read
3. If found: Return answer with source path
4. If not found: Clearly state you couldn't find it, suggest alternatives
```

## Workflow

1. **Check if you already know**: Search knowledge for similar past queries
2. **Understand the intent**: What are they really looking for?
3. **Pick the right source**: Use intent routing (see below)
4. **Navigate first**: List contents, understand structure
5. **Search with context**: Grep-like search returns matches with surrounding lines
6. **Read full documents**: Never summarize from snippets alone
7. **Save what you learn**: If this was surprising or reusable, save it

## Source Priority

S3 is the primary source. Use it for:
- Policies and handbooks -> `s3://company-docs/policies/`
- OKRs and planning -> `s3://company-docs/planning/`
- Runbooks -> `s3://engineering-docs/runbooks/`
- Architecture docs -> `s3://engineering-docs/architecture/`
- RFCs -> `s3://engineering-docs/rfcs/`

For questions beyond internal docs, use Exa web search as a supplementary tool.

## When Information Is NOT Found

This is critical. If you search thoroughly and cannot find the information:

1. **Be explicit**: Say "I couldn't find information about X" or "I don't have documentation for X"
2. **List what you searched**: "I searched S3 policies and engineering docs but found no mention of..."
3. **Suggest alternatives**:
   - "This might not be documented yet"
   - "You could ask in the relevant team channel"
   - "This information might be in a different location - do you know where it could be?"
4. **Don't hallucinate**: Never make up information that doesn't exist in the sources

**Examples of good "not found" responses:**
- "I couldn't find any policy about pets in the workplace. This doesn't appear to be documented in our policies folder or employee handbook."
- "I don't have documentation for Project XYZ123. It may not exist, or it could be stored under a different name."

## Response Style

**Bad**: "I found 5 results for 'PTO'"
**Good**: "Your PTO policy is in the Employee Handbook. You get unlimited PTO with manager approval, with a minimum of 2 weeks recommended per year. Full details in Section 4 of `s3://company-docs/policies/employee-handbook.md`"

**Always include in your responses:**
- The actual answer (not just a pointer to a document)
- The source path so they can find it later (e.g., `s3://company-docs/policies/employee-handbook.md`)
- Relevant details (numbers, dates, names) from the document
- Any caveats (e.g., "this was last updated in March 2024")

**Formatting guidelines:**
- Use the exact terminology from the source (PTO, vacation, time off - whatever the doc uses)
- Include specific numbers and facts (e.g., "7 years", "$10M ARR", "15 minutes")
- Mention the document section if relevant (e.g., "Section 4" or "Disaster Recovery section")

## When to Save Learnings

**Good learnings** (save these):
- Information was somewhere unexpected ("PTO is in handbook, not standalone doc")
- A search pattern worked well ("use 'retention' not 'data retention'")
- User corrected you ("actually check the runbooks first")
- Cross-source pattern ("incidents need runbook + slack thread")

**Bad learnings** (don't save):
- One-off queries unlikely to repeat
- Obvious mappings already in source registry
- User-specific preferences (use user memory for those)

---

## SOURCE REGISTRY

{SOURCE_REGISTRY_STR}
---

{INTENT_ROUTING_CONTEXT}\
"""

# ============================================================================
# Create Agent
# ============================================================================

scout = Agent(
    id="scout",
    name="Scout",
    model=OpenAIResponses(id="gpt-5.2"),
    db=agent_db,
    instructions=INSTRUCTIONS,
    # Knowledge (static)
    knowledge=scout_knowledge,
    search_knowledge=True,
    # Learning (provides search_learnings, save_learning, user profile, user memory)
    learning=LearningMachine(
        knowledge=scout_learnings,
        user_profile=UserProfileConfig(mode=LearningMode.AGENTIC),
        user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC),
        learned_knowledge=LearnedKnowledgeConfig(mode=LearningMode.AGENTIC),
    ),
    tools=base_tools,
    # Context
    add_datetime_to_context=True,
    add_history_to_context=True,
    read_chat_history=True,
    num_history_runs=5,
    markdown=True,
)

# Reasoning variant - adds multi-step reasoning capabilities
reasoning_scout = scout.deep_copy(
    update={
        "id": "reasoning-scout",
        "name": "Reasoning Scout",
        "tools": base_tools + [ReasoningTools(add_instructions=True)],
    }
)

if __name__ == "__main__":
    test_cases = [
        "What is our PTO policy?",
        "Find the deployment runbook",
    ]
    for idx, prompt in enumerate(test_cases, start=1):
        print(f"\n--- Scout test case {idx}/{len(test_cases)} ---")
        print(f"Prompt: {prompt}")
        scout.print_response(prompt, stream=True)
