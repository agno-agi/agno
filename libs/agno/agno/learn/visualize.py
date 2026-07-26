"""Visualize an entity-memory graph.

Renders the entities and relationships an :class:`EntityMemoryStore` holds, two
ways:

- ``render_terminal``: a rich tree per entity - its live facts (with as-of
  dates), superseded facts struck through, and its outgoing/incoming links by
  name.
- ``render_html``: a self-contained, interactive force-directed graph written
  to a file (no external requests), nodes colored by entity_type and edges
  labeled by relation.

The point is to SEE what the four tools actually wrote: reciprocal edges on
both ends, supersession retiring a fact without deleting it, and archived
entities still present. It reads through the store's own ``list_entities``, so
it works on sqlite and postgres alike.

Accepts an ``Agent`` (with ``learning=``), a ``LearningMachine``, or an
``EntityMemoryStore`` directly::

    from agno.learn import show_entity_graph

    show_entity_graph(agent, namespace="my_namespace", html="tmp/graph.html")
"""

from __future__ import annotations

import html as _html
import json
import os
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Reading the store
# ---------------------------------------------------------------------------


def _resolve_store(source: Any) -> Any:
    """Accept an Agent, a LearningMachine, or an EntityMemoryStore directly."""
    # EntityMemoryStore already
    if hasattr(source, "list_entities") and hasattr(source, "search"):
        return source
    # Agent -> its LearningMachine (``_learning``), or a machine passed directly.
    machine = getattr(source, "_learning", None) or getattr(source, "learning_machine", None) or source
    store = getattr(machine, "entity_memory_store", None)
    if store is not None and hasattr(store, "list_entities"):
        return store
    # Fall back: scan the machine's stores dict for the entity one.
    stores = getattr(machine, "stores", None) or {}
    for candidate in stores.values():
        if hasattr(candidate, "list_entities") and hasattr(candidate, "search"):
            return candidate
    raise ValueError(
        "Could not find an EntityMemoryStore on the given object. Pass an agent "
        "with learning=LearningMachine(entity_memory=...), the machine, or the store."
    )


def _load_entities(
    source: Any,
    namespace: Optional[str],
    user_id: Optional[str],
    limit: int,
) -> List[Any]:
    store = _resolve_store(source)
    return store.list_entities(
        namespace=namespace,
        user_id=user_id,
        limit=limit,
        include_archived=True,
    )


def _live_facts(entity: Any) -> List[dict]:
    return [f for f in (entity.facts or []) if isinstance(f, dict) and not f.get("superseded_at")]


def _dead_facts(entity: Any) -> List[dict]:
    return [f for f in (entity.facts or []) if isinstance(f, dict) and f.get("superseded_at")]


def _as_of(fact: dict) -> str:
    stamp = str(fact.get("updated_at") or fact.get("created_at") or "")[:10]
    return f" (as of {stamp})" if stamp else ""


def _display(entity: Any) -> str:
    return entity.name or entity.entity_id


# ---------------------------------------------------------------------------
# Terminal rendering (rich)
# ---------------------------------------------------------------------------

# Stable, high-contrast colors keyed by entity_type. Unknown types cycle
# through the tail so the graph stays readable however many types appear.
_TYPE_COLORS = {
    "person": "bright_cyan",
    "project": "bright_green",
    "company": "bright_yellow",
    "system": "bright_magenta",
    "product": "bright_blue",
    "team": "cyan",
    "unknown": "grey58",
}
_FALLBACK_COLORS = ["red", "green", "yellow", "blue", "magenta", "cyan"]


def _color_for(entity_type: str, seen: Dict[str, str]) -> str:
    if entity_type in _TYPE_COLORS:
        return _TYPE_COLORS[entity_type]
    if entity_type not in seen:
        seen[entity_type] = _FALLBACK_COLORS[len(seen) % len(_FALLBACK_COLORS)]
    return seen[entity_type]


def render_terminal(entities: List[Any]) -> None:
    """Print a rich tree per entity: facts, superseded facts, and links by name."""
    from rich.console import Console
    from rich.tree import Tree

    console = Console()
    if not entities:
        console.print("[yellow]No entities found in this namespace.[/yellow]")
        return

    by_id = {e.entity_id: e for e in entities}
    seen_types: Dict[str, str] = {}

    header = f"Entity graph - {len(entities)} entities"
    console.print(f"\n[bold]{header}[/bold]")
    console.print("[dim]" + "-" * len(header) + "[/dim]")

    for entity in entities:
        color = _color_for(entity.entity_type, seen_types)
        archived = " [dim](archived)[/dim]" if getattr(entity, "archived_at", None) else ""
        label = f"[bold {color}]{_display(entity)}[/bold {color}] [dim]{entity.entity_type}[/dim]{archived}"
        tree = Tree(label)

        if entity.description:
            tree.add(f"[italic dim]{entity.description}[/italic dim]")

        live = _live_facts(entity)
        if live:
            facts_branch = tree.add("[bold]facts[/bold]")
            for fact in live:
                facts_branch.add(f"{fact.get('content', '')}[dim]{_as_of(fact)}[/dim]")

        dead = _dead_facts(entity)
        if dead:
            retired = tree.add("[dim]superseded[/dim]")
            for fact in dead:
                retired.add(f"[strike dim]{fact.get('content', '')}[/strike dim]")

        edges = [r for r in (entity.relationships or []) if isinstance(r, dict)]
        if edges:
            links_branch = tree.add("[bold]links[/bold]")
            for edge in edges:
                far_id = str(edge.get("entity_id", ""))
                far = by_id.get(far_id)
                far_name = _display(far) if far else far_id
                relation = edge.get("relation", "")
                if edge.get("direction") == "incoming":
                    links_branch.add(f"[dim]<--[/dim] {far_name} [dim]{relation}[/dim]")
                else:
                    links_branch.add(f"[dim]--{relation}-->[/dim] {far_name}")

        console.print(tree)

    # Legend
    console.print("\n[dim]types:[/dim] ", end="")
    legend_types = {e.entity_type for e in entities}
    parts = [f"[{_color_for(t, seen_types)}]{t}[/{_color_for(t, seen_types)}]" for t in sorted(legend_types)]
    console.print("  ".join(parts))


# ---------------------------------------------------------------------------
# HTML rendering (self-contained, no external requests)
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Entity Graph</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ margin: 0; font: 14px/1.5 -apple-system, system-ui, sans-serif;
          background: #0d1117; color: #e6edf3; }}
  #wrap {{ display: flex; height: 100vh; }}
  #graph {{ flex: 1; }}
  #side {{ width: 320px; padding: 16px 20px; overflow-y: auto;
           border-left: 1px solid #30363d; box-sizing: border-box; }}
  h1 {{ font-size: 16px; margin: 0 0 4px; }}
  .muted {{ color: #8b949e; }}
  .swatch {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%;
             margin-right: 6px; vertical-align: middle; }}
  .legend div {{ margin: 3px 0; }}
  #detail h2 {{ font-size: 15px; margin: 14px 0 4px; }}
  #detail .fact {{ margin: 2px 0; }}
  #detail .dead {{ text-decoration: line-through; color: #8b949e; }}
  #detail .edge {{ color: #8b949e; }}
  svg text {{ fill: #e6edf3; font-size: 11px; }}
  line.link {{ stroke: #484f58; stroke-width: 1.4px; }}
  text.rel {{ fill: #8b949e; font-size: 9px; }}
  circle.node {{ cursor: pointer; stroke: #0d1117; stroke-width: 2px; }}
  circle.archived {{ stroke-dasharray: 3 2; opacity: 0.55; }}
</style></head>
<body><div id="wrap">
  <svg id="graph"></svg>
  <div id="side">
    <h1>Entity graph</h1>
    <div class="muted">{count} entities &middot; drag nodes &middot; click for detail</div>
    <div class="legend" id="legend"></div>
    <div id="detail"><p class="muted">Click a node.</p></div>
  </div>
</div>
<script>
const DATA = {data};
const COLORS = {{person:"#39c5cf",project:"#3fb950",company:"#d29922",system:"#bc8cff",
  product:"#58a6ff",team:"#1f9ede",unknown:"#8b949e"}};
const fallback = ["#f85149","#3fb950","#d29922","#58a6ff","#bc8cff","#39c5cf"];
const typeColor = (() => {{ const seen={{}}; let i=0;
  return t => COLORS[t] || (seen[t] ??= fallback[i++ % fallback.length]); }})();

const svg = document.getElementById("graph");
const W = () => svg.clientWidth, H = () => svg.clientHeight;
const NS = "http://www.w3.org/2000/svg";
const el = (n, a) => {{ const e = document.createElementNS(NS, n);
  for (const k in a) e.setAttribute(k, a[k]); return e; }};

// De-duplicate reciprocal edges into a single drawn line.
const nodes = DATA.nodes.map(n => ({{...n, x: Math.random()*W(), y: Math.random()*H(), vx:0, vy:0}}));
const idx = Object.fromEntries(nodes.map((n,i) => [n.id, i]));
const seen = new Set(); const links = [];
for (const e of DATA.edges) {{
  const key = [e.source, e.target].sort().join("|") + "|" + e.relation;
  if (seen.has(key)) continue; seen.add(key);
  if (idx[e.source] === undefined || idx[e.target] === undefined) continue;
  links.push({{source: idx[e.source], target: idx[e.target], relation: e.relation}});
}}

// Arrowhead marker (drawn at the target end so the relation reads source -> target).
const defs = el("defs");
const marker = el("marker", {{id:"arrow", viewBox:"0 0 10 10", refX:"9", refY:"5",
  markerWidth:"7", markerHeight:"7", orient:"auto-start-reverse"}});
marker.append(el("path", {{d:"M 0 0 L 10 5 L 0 10 z", fill:"#6e7681"}}));
defs.append(marker); svg.append(defs);

const linkG = el("g"); const nodeG = el("g"); svg.append(linkG, nodeG);
const lineEls = links.map(() => {{ const l = el("line", {{class:"link", "marker-end":"url(#arrow)"}}); linkG.append(l); return l; }});
const relEls = links.map(l => {{ const t = el("text", {{class:"rel"}}); t.textContent = l.relation; linkG.append(t); return t; }});
const nodeEls = nodes.map(n => {{
  const g = el("g");
  const c = el("circle", {{class:"node" + (n.archived ? " archived":""), r:14, fill: typeColor(n.type)}});
  const t = el("text", {{"text-anchor":"middle", dy:"-1.4em"}}); t.textContent = n.label;
  c.addEventListener("click", () => showDetail(n));
  g.append(c, t); nodeG.append(g);
  return {{g, c}};
}});

// Minimal force sim: repulsion + link springs + centering.
function tick() {{
  for (let i=0;i<nodes.length;i++) {{
    const a = nodes[i];
    for (let j=i+1;j<nodes.length;j++) {{
      const b = nodes[j]; let dx=a.x-b.x, dy=a.y-b.y; let d2=dx*dx+dy*dy||1;
      const f = 2200/d2; const d=Math.sqrt(d2);
      a.vx += f*dx/d; a.vy += f*dy/d; b.vx -= f*dx/d; b.vy -= f*dy/d;
    }}
    a.vx += (W()/2 - a.x)*0.002; a.vy += (H()/2 - a.y)*0.002;
  }}
  for (const l of links) {{
    const a=nodes[l.source], b=nodes[l.target];
    let dx=b.x-a.x, dy=b.y-a.y; let d=Math.sqrt(dx*dx+dy*dy)||1;
    const f=(d-120)*0.01; a.vx+=f*dx/d; a.vy+=f*dy/d; b.vx-=f*dx/d; b.vy-=f*dy/d;
  }}
  for (const n of nodes) {{
    if (n.fixed) continue;
    n.x += (n.vx *= 0.85); n.y += (n.vy *= 0.85);
    n.x = Math.max(20, Math.min(W()-20, n.x)); n.y = Math.max(30, Math.min(H()-20, n.y));
  }}
  links.forEach((l,i) => {{
    const a=nodes[l.source], b=nodes[l.target];
    // Stop the line (and its arrowhead) at the target node's rim, not its center.
    let dx=b.x-a.x, dy=b.y-a.y; let d=Math.hypot(dx,dy)||1; let r=18;
    const tx=b.x-dx/d*r, ty=b.y-dy/d*r;
    lineEls[i].setAttribute("x1",a.x); lineEls[i].setAttribute("y1",a.y);
    lineEls[i].setAttribute("x2",tx); lineEls[i].setAttribute("y2",ty);
    relEls[i].setAttribute("x",(a.x+b.x)/2); relEls[i].setAttribute("y",(a.y+b.y)/2);
  }});
  nodes.forEach((n,i) => nodeEls[i].g.setAttribute("transform", `translate(${{n.x}},${{n.y}})`));
  requestAnimationFrame(tick);
}}
tick();

// Drag
let dragging = null;
svg.addEventListener("mousedown", e => {{
  const hit = nodes.map((n,i)=>({{n,i,d:Math.hypot(n.x-e.offsetX,n.y-e.offsetY)}}))
                   .filter(o=>o.d<16).sort((a,b)=>a.d-b.d)[0];
  if (hit) {{ dragging = hit.n; dragging.fixed = true; }}
}});
svg.addEventListener("mousemove", e => {{ if (dragging) {{ dragging.x=e.offsetX; dragging.y=e.offsetY; }} }});
window.addEventListener("mouseup", () => {{ if (dragging) dragging.fixed=false; dragging=null; }});

function showDetail(n) {{
  const facts = (n.facts||[]).map(f =>
    `<div class="fact ${{f.dead?'dead':''}}">${{f.content}}${{f.asof?` <span class="muted">${{f.asof}}</span>`:''}}</div>`).join("");
  const edges = (n.edges||[]).map(e =>
    `<div class="edge">${{e.dir==='incoming'?'&larr; ':'&rarr; '}}${{e.relation}} &middot; ${{e.name}}</div>`).join("");
  document.getElementById("detail").innerHTML =
    `<h2><span class="swatch" style="background:${{typeColor(n.type)}}"></span>${{n.label}}` +
    `${{n.archived?' <span class="muted">(archived)</span>':''}}</h2>` +
    `<div class="muted">${{n.type}}</div>` +
    (n.description?`<p>${{n.description}}</p>`:"") +
    (facts?`<h2>facts</h2>${{facts}}`:"") + (edges?`<h2>links</h2>${{edges}}`:"");
}}

const types = [...new Set(nodes.map(n=>n.type))].sort();
document.getElementById("legend").innerHTML = types.map(t =>
  `<div><span class="swatch" style="background:${{typeColor(t)}}"></span>${{t}}</div>`).join("");
</script></body></html>
"""


def _entity_to_node(entity: Any, by_id: Dict[str, Any]) -> dict:
    facts = []
    for f in _live_facts(entity):
        facts.append({"content": _html.escape(str(f.get("content", ""))), "asof": _as_of(f).strip(), "dead": False})
    for f in _dead_facts(entity):
        facts.append({"content": _html.escape(str(f.get("content", ""))), "asof": "", "dead": True})

    edges = []
    for edge in entity.relationships or []:
        if not isinstance(edge, dict):
            continue
        far = by_id.get(str(edge.get("entity_id", "")))
        edges.append(
            {
                "relation": _html.escape(str(edge.get("relation", ""))),
                "dir": edge.get("direction", "outgoing"),
                "name": _html.escape(_display(far) if far else str(edge.get("entity_id", ""))),
            }
        )

    return {
        "id": entity.entity_id,
        "label": _html.escape(_display(entity)),
        "type": entity.entity_type,
        "description": _html.escape(entity.description) if entity.description else "",
        "archived": bool(getattr(entity, "archived_at", None)),
        "facts": facts,
        "edges": edges,
    }


def render_html(entities: List[Any], path: str) -> str:
    """Write a self-contained interactive HTML graph to ``path``. Returns the path."""
    by_id = {e.entity_id: e for e in entities}
    nodes = [_entity_to_node(e, by_id) for e in entities]

    edges = []
    for entity in entities:
        for edge in entity.relationships or []:
            if not isinstance(edge, dict):
                continue
            if edge.get("direction") == "incoming":
                continue  # draw each reciprocal pair once, from the outgoing side
            edges.append(
                {
                    "source": entity.entity_id,
                    "target": str(edge.get("entity_id", "")),
                    "relation": str(edge.get("relation", "")),
                }
            )

    data = json.dumps({"nodes": nodes, "edges": edges})
    doc = _HTML_TEMPLATE.format(data=data, count=len(nodes))

    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    return path


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def show_entity_graph(
    source: Any,
    namespace: Optional[str] = None,
    user_id: Optional[str] = None,
    limit: int = 200,
    html: Optional[str] = None,
    terminal: bool = True,
) -> List[Any]:
    """Render an entity-memory graph. Returns the entities it loaded.

    Args:
        source: An Agent (with ``learning=``), a LearningMachine, or an EntityMemoryStore.
        namespace: The namespace to read (defaults to the store's configured one).
        user_id: Required only for the 'user' namespace.
        limit: Max entities to load.
        html: If given, also write an interactive HTML graph to this path.
        terminal: Print the rich terminal view (default True).

    Returns:
        The list of loaded ``EntityMemory`` objects (archived included).
    """
    entities = _load_entities(source, namespace=namespace, user_id=user_id, limit=limit)
    if terminal:
        render_terminal(entities)
    if html:
        out = render_html(entities, html)
        from agno.utils.log import log_info

        log_info(f"Entity graph written to: {out}")
    return entities
