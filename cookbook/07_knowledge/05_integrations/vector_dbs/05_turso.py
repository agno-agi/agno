"""
Turso: Native Vector Search
===========================
Turso is a from-scratch, SQLite-compatible database (the engine behind the
`pyturso` driver) that supports vector similarity search natively
(vector32() + vector_distance_cos), so you get vectors alongside your relational
data in a single local database file.

Features:
- Vector similarity search (cosine / L2), no extension required
- Reranking support
- Local Turso database file

Notes:
- The current Turso engine has no FTS5, so TursoVector is vector-only
  (no keyword / hybrid search) and has no ANN index (exact/full-scan search).

Requires: pip install "pyturso[sqlalchemy]"   (or: pip install "agno[turso]")
"""

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.turso import TursoVector

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

# Vector search over a local Turso database file.
knowledge = Knowledge(
    vector_db=TursoVector(
        table_name="turso_vectors",
        db_file="tmp/turso_vector.db",
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cv_path = "cookbook/07_knowledge/testing_resources/cv_1.pdf"

    print("\n" + "=" * 60)
    print("Turso: Vector search")
    print("=" * 60 + "\n")

    knowledge.insert(path=cv_path)
    agent = Agent(
        model=OpenAIResponses(id="gpt-5.5"),
        knowledge=knowledge,
        search_knowledge=True,
        markdown=True,
    )
    agent.print_response("What work experience does this candidate have?", stream=True)
