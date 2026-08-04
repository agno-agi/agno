# Test Log: 04_entity_memory

> Tested 2026-07-25 against gpt-5.5 (OpenAIResponses), branch feat/entity-memory-revamp,
> Postgres (pgvector container on 5532). Rebuilt on the four-tool surface.

### 01_the_four_tools.py

**Status:** PASS

**Description:** Capture (facts + events + link via remember_about/link_entities), a
correction, and relevance recall in a fresh session.

**Result:** Turn 2's "radar shipped v1" retired the "blocked on security review" fact via
supersession (tool reply: "Superseded 1 earlier fact(s)"); the live-facts print shows only
"status: v1 shipped to production (as of 2026-07-25)" plus the reciprocal designer edge.
Turn 3 in a fresh session recalled radar through the message-driven path and answered from
the injected block. Model behavior note: the agent also chose to record the ship as both a
fact (status line) and an event - exactly the intended split.

Earlier phrasing note (kept for honesty): with turn 2 phrased "no longer using Postgres, we
switched to SQLite for the prototype", the judge did NOT supersede "uses Postgres" -
it read "for the prototype" as scoping that can coexist with prod Postgres. Defensible
conservatism; the demo now uses the unambiguous blocked->shipped correction.

---

### 02_links_and_forget.py

**Status:** PASS

**Description:** Reciprocal links, one-hop names, browse-by-recency, archive via forget.

**Result:** The edge landed on both rows with the far end's type (radar: "designs <-
sarah_chen"; sarah_chen: outgoing twin). Browse turn listed all tracked entities with the
directory. The archive turn called forget; the explicit search then showed
"**radar project** (project) (archived)" while the entity left the directory. Model
behavior note: the agent named the entity "radar project" (slug radar_project) rather than
"radar" - consistent within the run, and resolution keeps later variants merged.

---
