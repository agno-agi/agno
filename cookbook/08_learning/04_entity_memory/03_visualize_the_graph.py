"""
Entity Memory: Visualize the Graph
==================================
A review aid. It builds a small world through the four tools, then renders it
so you can SEE what entity memory actually wrote:

- reciprocal links (the same edge from both ends),
- fact supersession (a corrected fact retired, struck through, NOT deleted),
- archive (a forgotten entity still present, marked archived).

It drives the store directly (remember_about / link_entities / forget) rather
than through an LLM, so it is deterministic and needs no API key - the point
here is the visualization, not model behavior. For the model-driven versions
see 01_the_four_tools.py and 02_links_and_forget.py.

Two views, from the SDK helper agno.learn.show_entity_graph:
- terminal: a rich tree per entity (facts, superseded facts, links by name),
- html: an interactive force-directed graph written to a file.

Run:
    .venvs/demo/bin/python cookbook/08_learning/04_entity_memory/03_visualize_the_graph.py
"""

from uuid import uuid4

from agno.db.postgres import PostgresDb
from agno.learn import EntityMemoryConfig, LearningMachine, show_entity_graph

# ---------------------------------------------------------------------------
# Build the machine (no agent, no model - we call the store's tools directly)
# ---------------------------------------------------------------------------

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# Fresh per-run namespace so the demo starts clean on every execution.
NAMESPACE = f"viz_{uuid4().hex[:6]}"

machine = LearningMachine(
    db=db,
    entity_memory=EntityMemoryConfig(namespace=NAMESPACE),
)
store = machine.entity_memory_store


# ---------------------------------------------------------------------------
# Seed a small world
# ---------------------------------------------------------------------------


def build_world() -> None:
    # People
    store.remember_about(
        entity="Sarah Chen",
        entity_type="person",
        facts=["Leads the radar project", "Prefers async standups"],
        namespace=NAMESPACE,
    )
    store.remember_about(
        entity="Tom Alvarez",
        entity_type="person",
        facts=["Runs the infra platform"],
        namespace=NAMESPACE,
    )

    # Projects and systems
    store.remember_about(
        entity="Radar",
        entity_type="project",
        description="Threat-detection service",
        facts=["Blocked on security review"],
        namespace=NAMESPACE,
    )
    store.remember_about(
        entity="Infra Platform",
        entity_type="system",
        facts=["Runs on Kubernetes"],
        namespace=NAMESPACE,
    )
    store.remember_about(
        entity="Acme Corp",
        entity_type="company",
        facts=["Uses PostgreSQL"],
        namespace=NAMESPACE,
    )

    # A correction: stating the new status retires the stale one (supersession).
    # With no model configured the store cannot judge contradictions, so here we
    # make the correction explicit: record the new fact, retire the old by name.
    store.remember_about(
        entity="Radar",
        entity_type="project",
        facts=["Shipped to production"],
        namespace=NAMESPACE,
    )
    store.forget(entity="Radar", fact="Blocked on security review", namespace=NAMESPACE)

    # Links - each edge lands on BOTH entities (reciprocal).
    store.link_entities(
        entity="Sarah Chen",
        relation="designs",
        related_entity="Radar",
        namespace=NAMESPACE,
    )
    store.link_entities(
        entity="Tom Alvarez",
        relation="runs",
        related_entity="Infra Platform",
        namespace=NAMESPACE,
    )
    store.link_entities(
        entity="Radar",
        relation="depends_on",
        related_entity="Infra Platform",
        namespace=NAMESPACE,
    )
    store.link_entities(
        entity="Radar",
        relation="owned_by",
        related_entity="Acme Corp",
        namespace=NAMESPACE,
    )

    # Archive one entity - forget without a fact archives the whole entity
    # (reversible; a later remember_about revives it).
    store.remember_about(
        entity="Legacy Monolith",
        entity_type="system",
        facts=["Deprecated in Q1"],
        namespace=NAMESPACE,
    )
    store.forget(entity="Legacy Monolith", namespace=NAMESPACE)


# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"Namespace: {NAMESPACE}\n")
    build_world()

    # Terminal tree + an interactive HTML graph.
    show_entity_graph(machine, namespace=NAMESPACE, html="tmp/entity_graph.html")

    print("\nWhat to look for:")
    print("  - Radar: 'Shipped to production' is live; 'Blocked on security review'")
    print("    is under 'superseded' (struck through) - retired, not deleted.")
    print("  - Every link shows on both ends: Sarah --designs--> Radar, and")
    print("    Radar <-- Sarah designs.")
    print("  - Legacy Monolith is marked (archived) but still present.")
