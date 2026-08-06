"""
Give Studio-created Agents isolated knowledge
==============================================

Register one templated KnowledgeTools toolkit, then attach that toolkit to two
Studio-created Agents by its registry name. At tool-call time, each Agent uses
its own ``corpora/{agent_id}`` namespace over the shared PostgreSQL tables.

Prerequisites: ./cookbook/scripts/run_pgvector.sh
Run: .venvs/demo/bin/python cookbook/05_agent_os/22_studio/per_agent_knowledge.py
Try: rerun with --agent-id <printed-id> --message "Remember this text: ..."
"""

import argparse
import json
import os
from typing import Any, Dict
from uuid import uuid4

from agno.db.postgres import PostgresDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.registry import Registry
from agno.tools.knowledge import KnowledgeTools
from agno.tools.studio import StudioTools
from agno.vectordb.pgvector import PgVector

# ---------------------------------------------------------------------------
# Register one per-Agent knowledge building block
# ---------------------------------------------------------------------------

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://ai:ai@localhost:5532/ai",
)
db = PostgresDb(
    id="studio-per-agent-knowledge-db",
    db_url=DATABASE_URL,
    knowledge_table="studio_agent_knowledge_contents",
    components_table="studio_agent_knowledge_components",
    component_configs_table="studio_agent_knowledge_component_configs",
)

agent_knowledge = KnowledgeTools(
    name="agent_knowledge",
    knowledge=Knowledge(
        vector_db=PgVector(
            table_name="studio_agent_knowledge_vectors",
            db_url=DATABASE_URL,
            embedder=OpenAIEmbedder(),
        ),
        contents_db=db,
    ),
    namespace="corpora/{agent_id}",
    enable_add=True,
    enable_think=False,
    enable_analyze=False,
    instructions=(
        "Use search_knowledge to search this Agent's private corpus. "
        "Use add_text_to_knowledge only when the user asks to remember or index text."
    ),
)

registry = Registry(
    name="Per-Agent Knowledge Registry",
    tools=[agent_knowledge],
    models=[OpenAIResponses(id="gpt-5.5")],
    dbs=[db],
)

studio_tools = StudioTools(
    registry=registry,
    db=db,
    default_model_id="gpt-5.5",
)


# ---------------------------------------------------------------------------
# Build two Agents from the same registry primitive
# ---------------------------------------------------------------------------


def create_knowledge_agent(name: str) -> Dict[str, Any]:
    """Persist one Studio Agent wired to the templated knowledge toolkit."""
    result = json.loads(
        studio_tools.create_agent(
            name=name,
            instructions=(
                "Use add_text_to_knowledge to remember text only when asked. "
                "Use search_knowledge before answering questions about saved text."
            ),
            tool_names=["agent_knowledge"],
        )
    )
    if "error" in result:
        raise RuntimeError(result["error"])
    return result


def build_agents() -> None:
    """Create two persisted Agents that share configuration, not corpus data."""
    suffix = uuid4().hex[:8]
    agents = [
        create_knowledge_agent(f"Research Notes {suffix}"),
        create_knowledge_agent(f"Customer Notes {suffix}"),
    ]

    for agent in agents:
        print(f"Created: {agent['id']} with tools {agent['tools']}")
        print(f"Namespace configured for tool calls: corpora/{agent['id']}")

    print("No text was embedded by this setup run.")
    print(
        "Set OPENAI_API_KEY, then run either id with StudioTools.run_agent to add or search text."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-id", help="Run a previously created Studio Agent.")
    parser.add_argument("--message", help="Message for --agent-id.")
    args = parser.parse_args()

    if args.agent_id:
        if not args.message:
            parser.error("--message is required with --agent-id")
        print(studio_tools.run_agent(args.agent_id, args.message))
    else:
        build_agents()
