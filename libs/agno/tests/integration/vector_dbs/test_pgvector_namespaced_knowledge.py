"""Production-backend proof for per-Agent knowledge isolation.

Requires the cookbook PgVector service on localhost:5532. The deterministic
embedder keeps this test independent of provider credentials.
"""

import json
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

pytest.importorskip("pgvector")

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.embedder.base import Embedder
from agno.knowledge.knowledge import Knowledge
from agno.run import RunContext
from agno.tools.knowledge import KnowledgeTools
from agno.vectordb.pgvector import PgVector

PG_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"


def _postgres_reachable() -> bool:
    engine = create_engine(PG_URL, connect_args={"connect_timeout": 1})
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()


pytestmark = pytest.mark.skipif(not _postgres_reachable(), reason="PgVector is not reachable on localhost:5532")


class DeterministicEmbedder(Embedder):
    """Small deterministic embedding for database isolation tests."""

    dimensions: int = 3

    def get_embedding(self, text: str) -> List[float]:
        return [1.0, 0.0, 0.0]

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        return self.get_embedding(text), None

    async def async_get_embedding(self, text: str) -> List[float]:
        return self.get_embedding(text)

    async def async_get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        return self.get_embedding(text), None


@pytest.fixture
def namespaced_knowledge():
    schema = f"agent_knowledge_test_{uuid4().hex[:12]}"
    engine = create_engine(PG_URL)
    vector_db = PgVector(
        table_name="vectors",
        schema=schema,
        db_engine=engine,
        embedder=DeterministicEmbedder(dimensions=3),
    )
    contents_db = PostgresDb(
        id=f"contents-{schema}",
        db_engine=engine,
        db_schema=schema,
        knowledge_table="contents",
    )
    toolkit = KnowledgeTools(
        name="agent_knowledge",
        knowledge=Knowledge(vector_db=vector_db, contents_db=contents_db),
        namespace="corpora/{agent_id}",
        enable_think=False,
        enable_analyze=False,
        enable_add=True,
    )

    try:
        yield toolkit
    finally:
        vector_db.Session.remove()
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()


def test_pgvector_isolates_two_agent_corpora_in_shared_tables(namespaced_knowledge: KnowledgeTools):
    alpha = Agent(id="alpha", telemetry=False)
    beta = Agent(id="beta", telemetry=False)
    run_context = RunContext(run_id="run-1", session_id="session-1")

    for agent, private_text in ((alpha, "alpha secret"), (beta, "beta secret")):
        assert namespaced_knowledge.add_text_to_knowledge(run_context, "private", private_text, agent=agent).startswith(
            "Added"
        )
        assert namespaced_knowledge.add_text_to_knowledge(
            run_context, "same", "identical text", agent=agent
        ).startswith("Added")

    alpha_results = json.loads(namespaced_knowledge.search_knowledge(run_context, "secret", agent=alpha))
    beta_results = json.loads(namespaced_knowledge.search_knowledge(run_context, "secret", agent=beta))
    alpha_contents = namespaced_knowledge._resolved(run_context, alpha, None).get_content()[0]
    beta_contents = namespaced_knowledge._resolved(run_context, beta, None).get_content()[0]

    assert {document["content"] for document in alpha_results} == {"alpha secret", "identical text"}
    assert {document["content"] for document in beta_results} == {"beta secret", "identical text"}
    assert {content.id for content in alpha_contents}.isdisjoint({content.id for content in beta_contents})
    assert {content.name for content in alpha_contents} == {"private", "same"}
    assert {content.name for content in beta_contents} == {"private", "same"}

    assert namespaced_knowledge.add_text_to_knowledge(run_context, "private", "alpha updated", agent=alpha).startswith(
        "Added"
    )
    alpha_updated = json.loads(namespaced_knowledge.search_knowledge(run_context, "updated", agent=alpha))
    assert {document["content"] for document in alpha_updated} == {"alpha updated", "identical text"}
