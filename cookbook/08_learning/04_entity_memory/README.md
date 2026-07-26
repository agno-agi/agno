# 04_entity_memory

Deep-dive examples for entity memory: the agent's knowledge base about the
world (people, projects, companies, systems), revamped in 2.8.4 around four
tools with resolution, supersession and relevance recall in the store.

## Files

- `01_the_four_tools.py`: remember_about, a correction retiring a stale fact
  via supersession, and relevance recall in a fresh session.
- `02_links_and_forget.py`: reciprocal links with one-hop names on recall,
  browsing by recency, and archive/revive with forget.
- `03_visualize_the_graph.py`: builds a small world through the four tools and
  renders it (terminal tree + interactive HTML), so links, supersession and
  archive are visible at a glance. Deterministic, no API key.

## Visualizing the graph

`show_entity_graph` is an SDK helper (`agno.learn`). Point it at an agent, a
`LearningMachine`, or an `EntityMemoryStore`:

```python
from agno.learn import show_entity_graph

show_entity_graph(agent, namespace=NAMESPACE, html="tmp/graph.html")
```

It prints a rich tree (live facts, superseded facts struck through, links by
name) and, with `html=`, writes a self-contained interactive graph. Reads
through the store's own `list_entities`, so it works on sqlite and postgres.

## The four tools

| Tool | Job |
|---|---|
| `remember_about` | Upsert an entity by name: facts, events, description, `note=` pointer |
| `link_entities` | Record a relationship; the edge lands on both entities |
| `search_entities` | Find entities; with no query, list by recency (browse) |
| `forget` | Retire a fact, or archive a whole entity (reversible) |

There are no ids to invent and no fact ids to track: resolution (slugified
ids, aliases, normalized types) and correction (fact supersession with as-of
dates) are the store's job.
