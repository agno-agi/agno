# 04_entity_memory

Deep-dive examples for entity memory: the agent's knowledge base about the
world (people, projects, companies, systems), revamped in 2.8.4 around four
tools with resolution, supersession and relevance recall in the store.

## Files

- `01_the_four_tools.py`: remember_about, a correction retiring a stale fact
  via supersession, and relevance recall in a fresh session.
- `02_links_and_forget.py`: reciprocal links with one-hop names on recall,
  browsing by recency, and archive/revive with forget.

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
