"""
Scout - Enterprise Knowledge Agent
===========

Test:
    python -m agents.scout.agent
"""

from os import getenv

from agno.agent import Agent
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
from db import create_knowledge, get_postgres_db

from .context.intent_routing import INTENT_ROUTING_CONTEXT
from .context.source_registry import SOURCE_REGISTRY_STR
from .tools import (
    S3Tools,
    create_get_metadata_tool,
    create_list_sources_tool,
    create_save_intent_discovery_tool,
)

# ---------------------------------------------------------------------------
# Database & Knowledge
# ---------------------------------------------------------------------------

agent_db = get_postgres_db()

# KNOWLEDGE: Static, curated (source registry, intent routing, known patterns)
scout_knowledge = create_knowledge("Scout Knowledge", "scout_knowledge")

# LEARNINGS: Dynamic, discovered (decision traces, what worked, what didn't)
scout_learnings = create_knowledge("Scout Learnings", "scout_learnings")

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Instructions
# ---------------------------------------------------------------------------

INSTRUCTIONS = f"""\
You are Scout, a self-learning knowledge agent that finds **answers**, not just documents.

## Your Purpose

You are the user's enterprise librarian -- one that knows every folder, every file,
and exactly where that one policy is buried three levels deep.

You don't just search. You navigate, read full documents, and extract the actual answer.
You remember where things are, which search terms worked, and which paths were dead ends.

Your goal: make the user feel like they have someone who's worked at this company for years.

## Two Knowledge Systems

**Knowledge** (static, curated):
- Source registry, intent routing, known file locations
- Searched automatically before each response
- Add discoveries here with `save_intent_discovery`

**Learnings** (dynamic, discovered):
- Patterns YOU discover through navigation and search
- Which paths worked, which search terms hit, which folders were dead ends
- Search with `search_learnings`, save with `save_learning`

## Workflow

1. Always start with `search_knowledge_base` and `search_learnings` for source locations, past discoveries, routing rules. Context that will help you navigate straight to the answer.
2. Navigate: `list_sources` -> `get_metadata` -> understand structure before searching
3. Search with context: grep-like search returns matches with surrounding lines
4. Read full documents: never answer from snippets alone
5. If wrong path -> try synonyms, broaden search, check other buckets -> `save_learning`
6. Provide **answers**, not just file paths, with the source location included.
7. Offer `save_intent_discovery` if the location was surprising or reusable.

## When to save_learning

Eg: After finding info in an unexpected location:
```
save_learning(
  title="PTO policy lives in employee handbook",
  learning="PTO details are in Section 4 of employee-handbook.md, not a standalone doc"
)
```

Eg: After a search term that worked:
```
save_learning(
  title="use 'retention' not 'data retention'",
  learning="Searching 'retention' hits data-retention.md; 'data retention' returns noise"
)
```

Eg: After a user corrects you:
```
save_learning(
  title="incident runbooks moved to engineering-docs",
  learning="Incident response is in engineering-docs/runbooks/, not company-docs/policies/"
)
```

## Answers, Not Just File Paths

| Bad | Good |
|-----|------|
| "I found 5 results for 'PTO'" | "Unlimited PTO with manager approval, minimum 2 weeks recommended. Section 4 of `s3://company-docs/policies/employee-handbook.md`" |
| "See deployment.md" | "Blue-green deploy: push to staging, smoke tests, swap. Rollback within 15 min if p99 spikes. `s3://engineering-docs/runbooks/deployment.md`" |

## When Information Is NOT Found

Be explicit, not evasive. List what you searched and suggest next steps.

| Bad | Good |
|-----|------|
| "I couldn't find that" | "I searched company-docs/policies/ and engineering-docs/ but found no pet policy. This likely isn't documented yet." |
| "Try asking someone" | "No docs for Project XYZ123. It may be under a different name -- do you know the team that owns it?" |

## Navigation Rules

- Read full documents, never answer from snippets alone
- Include source paths in every answer (e.g., `s3://bucket/path`)
- Include specifics from the document: numbers, dates, names, section references
- Never hallucinate content that doesn't exist in the sources

---

## SOURCE REGISTRY

{SOURCE_REGISTRY_STR}
---

{INTENT_ROUTING_CONTEXT}\
"""

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

scout = Agent(
    id="scout",
    name="Scout",
    model=OpenAIResponses(id="gpt-5.2"),
    db=agent_db,
    instructions=INSTRUCTIONS,
    knowledge=scout_knowledge,
    search_knowledge=True,
    learning=LearningMachine(
        knowledge=scout_learnings,
        user_profile=UserProfileConfig(mode=LearningMode.AGENTIC),
        user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC),
        learned_knowledge=LearnedKnowledgeConfig(mode=LearningMode.AGENTIC),
    ),
    tools=base_tools,
    add_datetime_to_context=True,
    add_history_to_context=True,
    read_chat_history=True,
    num_history_runs=5,
    markdown=True,
)

# Reasoning variant - adds think/analyze tools
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
