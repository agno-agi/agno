"""
Benchmark Report Generator
==========================

Renders results/summary.json into a self-contained HTML report:
no external scripts, all styling inline, Google Fonts with real fallbacks.

Usage:
    python cookbook/performance/report.py
    python cookbook/performance/report.py --results path/summary.json --out path/report.html
"""

import argparse
import html
import json
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Report Structure
# ---------------------------------------------------------------------------
# (benchmark name, display label, series) per group; series picks the bar color
GROUPS = [
    {
        "key": "instantiation",
        "title": "Instantiation",
        "unit": "us",
        "measure": "time",
        "blurb": (
            "Wall time to construct agents, teams and workflows. "
            "The statistics table also carries each benchmark's allocation peak."
        ),
        "rows": [
            ("instantiate_agent", "Agent", "sync"),
            ("instantiate_agent_with_tools", "Agent, 5 tools", "sync"),
            ("instantiate_team", "Team, 3 members", "sync"),
            ("instantiate_workflow", "Workflow, 2 steps", "sync"),
        ],
    },
    {
        "key": "run",
        "title": "Run loop overhead",
        "unit": "us",
        "measure": "time",
        "blurb": (
            "One full run against an in-process mock model: everything Agno does around the model call. "
            "Sync and async variants of the same scenario share a row pair."
        ),
        "rows": [
            ("run_agent", "Run", "sync"),
            ("arun_agent", "Run, async", "async"),
            ("run_agent_streaming", "Streaming run", "sync"),
            ("arun_agent_streaming", "Streaming run, async", "async"),
            ("run_agent_with_tools", "Tool-call run", "sync"),
            ("arun_agent_with_tools", "Tool-call run, async", "async"),
            ("run_agent_with_storage", "Run with storage", "sync"),
            ("arun_agent_with_storage", "Run with storage, async", "async"),
        ],
    },
    {
        "key": "import",
        "title": "Cold import",
        "unit": "ms",
        "measure": "time",
        "blurb": (
            "Import cost in a fresh process, interpreter startup subtracted. "
            "Paid once per process: this is the CLI and serverless cold-start tax."
        ),
        "rows": [
            ("import_agno", "import agno", "sync"),
            ("import_agno_agent", "from agno.agent import Agent", "sync"),
        ],
    },
    {
        "key": "memory",
        "title": "Memory footprint",
        "unit": "KiB",
        "measure": "memory",
        "blurb": (
            "Net resident memory per live agent, measured over batches of 1000 held alive. "
            "Smaller than the instantiation peak: transient allocations are freed."
        ),
        "rows": [
            ("memory_per_agent", "Agent", "sync"),
            ("memory_per_agent_with_tools", "Agent, 2 tools", "sync"),
        ],
    },
]

UNIT_SCALE = {"us": 1e6, "ms": 1e3, "KiB": 1024}


def comparison_groups(versions: dict) -> list:
    """Chart groups for the cross-framework comparison, labels carrying versions."""

    def label(name: str, package: str) -> str:
        version = versions.get(package)
        return name + " " + version if version else name

    agno = label("Agno", "agno")
    langgraph = label("LangGraph", "langgraph")
    pydantic_ai = label("PydanticAI", "pydantic-ai")
    crewai = label("CrewAI", "crewai")
    return [
        {
            "key": "cmp_construction",
            "metric": "Agent construction (1 tool)",
            "title": "Agent construction vs other frameworks",
            "unit": "us",
            "measure": "time",
            "ratio_to": "agno_instantiation",
            "blurb": (
                "One agent with an OpenAI model reference and one function tool, "
                "identical shape per framework, no network. Agno defers tool schema "
                "extraction to the first run; frameworks doing that work at "
                "construction pay it here."
            ),
            "rows": [
                ("agno_instantiation", agno, "sync"),
                ("langgraph_instantiation", langgraph, "other"),
                ("pydantic_ai_instantiation", pydantic_ai, "other"),
                ("crewai_instantiation", crewai, "other"),
            ],
        },
        {
            "key": "cmp_run",
            "metric": "Single-turn run (mocked model)",
            "title": "Single-turn run vs other frameworks",
            "unit": "us",
            "measure": "time",
            "ratio_to": "run_compare_agno",
            "blurb": (
                "One mocked single-turn run: short system prompt, one user message, "
                "no tools, each framework's own testing or custom-model interface "
                "returning a canned reply. Per-request orchestration overhead; "
                "numbers are per-framework floors at the model boundary."
            ),
            "rows": [
                ("run_compare_agno", agno, "sync"),
                ("run_compare_langgraph", langgraph, "other"),
                ("run_compare_pydantic_ai", pydantic_ai, "other"),
                ("run_compare_crewai", crewai, "other"),
            ],
        },
        {
            "key": "cmp_tool_run",
            "metric": "Tool-call run (mocked model)",
            "title": "Tool-call run vs other frameworks",
            "unit": "us",
            "measure": "time",
            "ratio_to": "tool_run_compare_agno",
            "blurb": (
                "One run with one real tool execution: the mocked model requests "
                "a tool call, the framework dispatches and executes the actual "
                "function, and a second model turn answers. Agno pays its "
                "deferred tool-schema extraction here rather than at "
                "construction. CrewAI is excluded: with a custom model its tool "
                "use goes through a version-internal text protocol a mock "
                "cannot fairly reproduce."
            ),
            "rows": [
                ("tool_run_compare_agno", agno, "sync"),
                ("tool_run_compare_langgraph", langgraph, "other"),
                ("tool_run_compare_pydantic_ai", pydantic_ai, "other"),
            ],
        },
        {
            "key": "cmp_multi_turn",
            "metric": "5-turn conversation, in-memory",
            "title": "Five-turn conversation vs other frameworks",
            "unit": "ms",
            "measure": "time",
            "ratio_to": "multi_turn_compare_agno",
            "blurb": (
                "One five-turn conversation with history carried by each "
                "framework's native in-memory mechanism: Agno with its session "
                "cache enabled over an in-memory database, LangGraph's "
                "InMemorySaver per thread, PydanticAI passing message_history, "
                "CrewAI chaining five tasks through task context. Each variant "
                "asserts the history actually accumulated; the durable "
                "benchmark below measures the persisted configuration."
            ),
            "rows": [
                ("multi_turn_compare_agno", agno, "sync"),
                ("multi_turn_compare_langgraph", langgraph, "other"),
                ("multi_turn_compare_pydantic_ai", pydantic_ai, "other"),
                ("multi_turn_compare_crewai", crewai, "other"),
            ],
        },
        {
            "key": "cmp_long_conversation",
            "metric": "25-turn conversation, in-memory",
            "title": "Twenty-five-turn conversation vs other frameworks",
            "unit": "ms",
            "measure": "time",
            "ratio_to": "long_conversation_compare_agno",
            "blurb": (
                "The five-turn benchmark extended to twenty-five turns, so costs "
                "that grow with history length dominate. Earlier revisions "
                "reported this as a loss; after the copy-on-write history and "
                "incremental run-persistence changes it measures a win over "
                "LangGraph's reference-holding in-memory checkpointer, with "
                "Agno's session cache enabled in the matched configuration."
            ),
            "rows": [
                ("long_conversation_compare_agno", agno, "sync"),
                ("long_conversation_compare_langgraph", langgraph, "other"),
                ("long_conversation_compare_pydantic_ai", pydantic_ai, "other"),
                ("long_conversation_compare_crewai", crewai, "other"),
            ],
        },
        {
            "key": "cmp_durable_conversation",
            "metric": "25-turn conversation, durable (SQLite)",
            "title": "Durable twenty-five-turn conversation vs other frameworks",
            "unit": "ms",
            "measure": "time",
            "ratio_to": "durable_conversation_compare_agno",
            "blurb": (
                "The twenty-five-turn conversation persisted to a SQLite "
                "database every turn: Agno with SqliteDb, LangGraph with "
                "SqliteSaver, both paying real serialization and database "
                "writes, both running SQLite's WAL journal mode. LangGraph "
                "still measures modestly faster; the per-turn serialization "
                "of growing session state is the known optimization target. "
                "PydanticAI ships no persistence layer and CrewAI has no "
                "conversation primitive, so neither appears here."
            ),
            "rows": [
                ("durable_conversation_compare_agno", agno, "sync"),
                ("durable_conversation_compare_langgraph", langgraph, "other"),
            ],
        },
        {
            "key": "cmp_import",
            "metric": "Cold import",
            "title": "Cold import vs other frameworks",
            "unit": "ms",
            "measure": "time",
            "ratio_to": "import_compare_agno",
            "blurb": (
                "Importing each framework's Agent entrypoint in a fresh process, "
                "interpreter startup subtracted."
            ),
            "rows": [
                ("import_compare_agno", agno, "sync"),
                ("import_compare_langgraph", langgraph, "other"),
                ("import_compare_pydantic_ai", pydantic_ai, "other"),
                ("import_compare_crewai", crewai, "other"),
            ],
        },
        {
            "key": "cmp_memory",
            "metric": "Construction memory peak",
            "title": "Construction memory peak vs other frameworks",
            "unit": "KiB",
            "measure": "memory",
            "ratio_to": "agno_instantiation",
            "blurb": "Peak allocations while constructing one agent, per framework.",
            "rows": [
                ("agno_instantiation", agno, "sync"),
                ("langgraph_instantiation", langgraph, "other"),
                ("pydantic_ai_instantiation", pydantic_ai, "other"),
                ("crewai_instantiation", crewai, "other"),
            ],
        },
    ]


# Row order for the headline comparison table: most decision-relevant first
COMPARISON_TABLE_ORDER = [
    "cmp_run",
    "cmp_tool_run",
    "cmp_multi_turn",
    "cmp_long_conversation",
    "cmp_durable_conversation",
    "cmp_construction",
    "cmp_memory",
    "cmp_import",
]


# ---------------------------------------------------------------------------
# Value Extraction
# ---------------------------------------------------------------------------
def stat(bench: dict, field: str, measure: str) -> float:
    result = bench.get("result") or {}
    key = field + ("_run_time" if measure == "time" else "_memory_usage")
    return float(result.get(key) or 0.0)


def fmt(value: float, unit: str) -> str:
    scaled = value * UNIT_SCALE[unit]
    if scaled >= 100:
        return format(scaled, ",.0f")
    if scaled >= 10:
        return format(scaled, ".1f")
    return format(scaled, ".2f")


# ---------------------------------------------------------------------------
# HTML Fragments
# ---------------------------------------------------------------------------
def render_group(group: dict, benchmarks: dict) -> str:
    rows = [
        (name, label, series)
        for name, label, series in group["rows"]
        if name in benchmarks and benchmarks[name].get("result")
    ]
    if not rows:
        return ""
    measure = group["measure"]
    unit = group["unit"]
    peak = max(stat(benchmarks[name], "p95", measure) for name, _, _ in rows) or 1.0

    has_async = any(series == "async" for _, _, series in rows)
    has_other = any(series == "other" for _, _, series in rows)
    legend = ""
    if has_async:
        legend = (
            '<div class="legend">'
            '<span class="legend-item"><span class="swatch swatch-sync"></span>sync</span>'
            '<span class="legend-item"><span class="swatch swatch-async"></span>async</span>'
            "</div>"
        )
    elif has_other:
        legend = (
            '<div class="legend">'
            '<span class="legend-item"><span class="swatch swatch-sync"></span>Agno</span>'
            '<span class="legend-item"><span class="swatch swatch-other"></span>other frameworks</span>'
            "</div>"
        )

    # Ratio column against a designated baseline row (comparison groups)
    ratio_base = 0.0
    if group.get("ratio_to") and group["ratio_to"] in benchmarks:
        ratio_base = stat(benchmarks[group["ratio_to"]], "median", measure)

    def ratio_text(median: float) -> str:
        if not ratio_base or median == ratio_base:
            return ""
        ratio = median / ratio_base
        return (format(ratio, ".1f") if ratio < 10 else format(ratio, ",.0f")) + "x"

    bar_html = []
    for name, label, series in rows:
        bench = benchmarks[name]
        median = stat(bench, "median", measure)
        p95 = stat(bench, "p95", measure)
        width = max(0.5, 100.0 * median / peak)
        tick = min(100.0, 100.0 * p95 / peak)
        ratio = ratio_text(median)
        ratio_html = '<span class="bar-ratio">' + ratio + "</span>" if ratio else ""
        bar_html.append(
            '<div class="bar-row" title="median '
            + fmt(median, unit)
            + " "
            + unit
            + " | p95 "
            + fmt(p95, unit)
            + " "
            + unit
            + '">'
            + '<span class="bar-label">'
            + html.escape(label)
            + "</span>"
            + '<span class="bar-track">'
            + '<span class="bar bar-'
            + series
            + '" style="width:'
            + format(width, ".2f")
            + '%"></span>'
            + '<span class="p95-tick" style="left:'
            + format(tick, ".2f")
            + '%"></span>'
            + "</span>"
            + '<span class="bar-value">'
            + fmt(median, unit)
            + '<span class="bar-unit"> '
            + unit
            + "</span>"
            + ratio_html
            + "</span>"
            + "</div>"
        )

    # Time groups also carry the per-run allocation peak in their stats table
    show_memory = measure == "time" and any(
        stat(benchmarks[name], "median", "memory") for name, _, _ in rows
    )

    table_rows = []
    for name, label, series in rows:
        bench = benchmarks[name]
        cells = [
            "<td>" + html.escape(label) + "</td>",
            '<td class="num">' + fmt(stat(bench, "median", measure), unit) + "</td>",
            '<td class="num">' + fmt(stat(bench, "p95", measure), unit) + "</td>",
            '<td class="num">' + fmt(stat(bench, "min", measure), unit) + "</td>",
            '<td class="num">' + fmt(stat(bench, "max", measure), unit) + "</td>",
        ]
        if show_memory:
            cells.append(
                '<td class="num">'
                + fmt(stat(bench, "median", "memory"), "KiB")
                + "</td>"
            )
        cells.append(
            '<td class="num">'
            + html.escape(str(bench.get("num_iterations", "")))
            + "</td>"
        )
        table_rows.append("<tr>" + "".join(cells) + "</tr>")

    memory_header = "<th>Peak KiB</th>" if show_memory else ""
    caption = (
        "Time values in " + unit + "; Peak KiB is the median allocation peak"
        if show_memory
        else "All values in " + unit
    )
    table = (
        '<details class="stats"><summary>Full statistics</summary><div class="table-wrap"><table>'
        + "<caption>"
        + caption
        + "</caption>"
        + "<thead><tr><th>Benchmark</th><th>Median</th><th>p95</th><th>Min</th><th>Max</th>"
        + memory_header
        + "<th>Iterations</th></tr></thead><tbody>"
        + "".join(table_rows)
        + "</tbody></table></div></details>"
    )

    extra = ""
    if group["key"] == "import":
        extra = render_import_offenders(benchmarks)

    return (
        '<section class="group">'
        + "<h2>"
        + html.escape(group["title"])
        + "</h2>"
        + '<p class="blurb">'
        + html.escape(group["blurb"])
        + "</p>"
        + legend
        + '<div class="chart">'
        + "".join(bar_html)
        + "</div>"
        + '<p class="axis-note">bar = median, tick = p95, axis scaled to group p95 max ('
        + unit
        + ")</p>"
        + table
        + extra
        + "</section>"
    )


def render_import_offenders(benchmarks: dict) -> str:
    bench = benchmarks.get("import_agno_agent") or benchmarks.get("import_agno")
    if not bench:
        return ""
    offenders = (bench.get("extra") or {}).get("importtime_top") or []
    if not offenders:
        return ""
    rows = []
    for entry in offenders[:10]:
        rows.append(
            "<tr><td><code>"
            + html.escape(str(entry.get("module", "")))
            + "</code></td>"
            + '<td class="num">'
            + format(entry.get("self_us", 0) / 1000, ".1f")
            + "</td>"
            + '<td class="num">'
            + format(entry.get("cumulative_us", 0) / 1000, ".1f")
            + "</td></tr>"
        )
    return (
        '<details class="stats"><summary>Slowest modules on the Agent import path</summary>'
        + '<div class="table-wrap"><table>'
        + "<thead><tr><th>Module</th><th>Self ms</th><th>Cumulative ms</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div></details>"
    )


def render_comparison_table(cmp_groups: list, benchmarks: dict) -> str:
    """The headline table: one row per metric, one column per framework,
    every non-Agno cell carrying its multiple of the Agno value."""
    groups_by_key = {group["key"]: group for group in cmp_groups}
    ordered = [
        groups_by_key[key] for key in COMPARISON_TABLE_ORDER if key in groups_by_key
    ]
    if not ordered:
        return ""

    # Column labels come from the first group that has all frameworks present
    framework_labels = [label for _, label, _ in ordered[0]["rows"]]

    header_cells = "<th>Metric</th>" + "".join(
        "<th>" + html.escape(label) + "</th>" for label in framework_labels
    )

    body_rows = []
    for group in ordered:
        measure = group["measure"]
        unit = group["unit"]
        baseline_name = group["rows"][0][0]
        baseline = stat(benchmarks.get(baseline_name, {}), "median", measure)
        cells = ["<td>" + html.escape(group["metric"]) + "</td>"]
        for name, _, series in group["rows"]:
            bench = benchmarks.get(name)
            if not bench or not bench.get("result"):
                cells.append("<td>-</td>")
                continue
            median = stat(bench, "median", measure)
            value_text = fmt(median, unit) + " " + unit
            if series == "sync" or not baseline:
                cells.append("<td><strong>" + value_text + "</strong></td>")
            else:
                ratio = median / baseline
                ratio_text = (
                    format(ratio, ".1f") if ratio < 10 else format(ratio, ",.0f")
                ) + "x"
                cells.append(
                    "<td>"
                    + value_text
                    + ' <span class="cell-ratio">('
                    + ratio_text
                    + ")</span></td>"
                )
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    return (
        '<section class="group">'
        + "<h2>Agno versus other frameworks</h2>"
        + '<p class="blurb">Medians from one sequential run with every framework in the same '
        + "environment on the same machine. Multiples are relative to Agno. Per-metric "
        + "methodology and full statistics follow below.</p>"
        + '<div class="headline-wrap"><table class="headline">'
        + "<thead><tr>"
        + header_cells
        + "</tr></thead><tbody>"
        + "".join(body_rows)
        + "</tbody></table></div>"
        + "</section>"
    )


def render_hero(benchmarks: dict) -> str:
    tiles = []

    def tile(label, value, unit, caption):
        tiles.append(
            '<div class="tile"><div class="tile-label">'
            + html.escape(label)
            + '</div><div class="tile-value">'
            + value
            + '<span class="tile-unit"> '
            + unit
            + "</span></div>"
            + '<div class="tile-caption">'
            + html.escape(caption)
            + "</div></div>"
        )

    if "instantiate_agent" in benchmarks:
        tile(
            "Agent instantiation",
            fmt(stat(benchmarks["instantiate_agent"], "median", "time"), "us"),
            "us",
            "median",
        )
    if "memory_per_agent" in benchmarks:
        tile(
            "Memory per agent",
            fmt(stat(benchmarks["memory_per_agent"], "median", "memory"), "KiB"),
            "KiB",
            "resident, median",
        )
    if "run_agent" in benchmarks:
        tile(
            "Run overhead",
            fmt(stat(benchmarks["run_agent"], "median", "time"), "us"),
            "us",
            "mock model, median",
        )
    if "import_agno_agent" in benchmarks:
        tile(
            "Cold import",
            fmt(stat(benchmarks["import_agno_agent"], "median", "time"), "ms"),
            "ms",
            "from agno.agent import Agent",
        )
    return '<div class="tiles">' + "".join(tiles) + "</div>"


def render_meta(machine: dict) -> str:
    chips = []
    for label in [
        ("agno " + str(machine.get("agno_version") or "unknown")),
        ("commit " + str(machine.get("git_commit") or "unknown")),
        ("python " + str(machine.get("python_version") or "unknown")),
        str(machine.get("processor") or machine.get("machine") or "unknown"),
        str(machine.get("measured_at", ""))[:10],
    ]:
        if label and not label.endswith("unknown"):
            chips.append('<span class="chip">' + html.escape(label) + "</span>")
    return '<div class="chips">' + "".join(chips) + "</div>"


def render_caveats(summary: dict) -> str:
    """Visible banner when the summary is not a clean full run."""
    notes = []
    if summary.get("quick"):
        notes.append(
            "Quick smoke run: iteration counts were reduced, numbers are not baseline quality."
        )
    failures = summary.get("failures") or []
    if failures:
        notes.append(
            "Failed benchmarks omitted: " + ", ".join(str(f) for f in failures) + "."
        )
    if not notes:
        return ""
    return '<div class="caveat">' + html.escape(" ".join(notes)) + "</div>"


# ---------------------------------------------------------------------------
# Page Template
# ---------------------------------------------------------------------------
CSS = """
:root {
  --bg: #0b0c0e;
  --surface: #15171b;
  --surface-2: #1c1f24;
  --hairline: #272b31;
  --ink: #f2f1ee;
  --ink-2: #9ca1a8;
  --ink-3: #6b7178;
  --accent: #ff4d0d;
  --series-sync: #f65a1e;
  --series-async: #5e8fd8;
  --series-other: #8a9099;
  --tick: #e8e6e1;
}
@media (prefers-color-scheme: light) {
  :root:not([data-theme="dark"]) {
    --bg: #faf9f7;
    --surface: #ffffff;
    --surface-2: #f1efec;
    --hairline: #e3e0db;
    --ink: #1b1c1e;
    --ink-2: #565b61;
    --ink-3: #8a9097;
    --accent: #e84b0c;
    --series-sync: #e85512;
    --series-async: #3b6bc4;
    --series-other: #767d85;
    --tick: #1b1c1e;
  }
}
:root[data-theme="light"] {
  --bg: #faf9f7;
  --surface: #ffffff;
  --surface-2: #f1efec;
  --hairline: #e3e0db;
  --ink: #1b1c1e;
  --ink-2: #565b61;
  --ink-3: #8a9097;
  --accent: #e84b0c;
  --series-sync: #e85512;
  --series-async: #3b6bc4;
  --series-other: #767d85;
  --tick: #1b1c1e;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: "Instrument Sans", "Helvetica Neue", Arial, sans-serif;
  line-height: 1.55;
  -webkit-font-smoothing: antialiased;
}
.page { max-width: 980px; margin: 0 auto; padding: 48px 24px 80px; }
header { margin-bottom: 40px; }
.eyebrow {
  font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px; letter-spacing: 0.14em; text-transform: uppercase;
  color: var(--accent); margin-bottom: 10px;
}
h1 {
  font-family: "Archivo", "Helvetica Neue", Arial, sans-serif;
  font-size: clamp(34px, 6vw, 52px); font-weight: 800;
  letter-spacing: -0.02em; line-height: 1.05; margin: 0 0 14px;
  text-wrap: balance;
}
.lede { color: var(--ink-2); max-width: 62ch; margin: 0 0 18px; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chip {
  font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px; color: var(--ink-2);
  background: var(--surface); border: 1px solid var(--hairline);
  padding: 4px 10px; border-radius: 999px;
}
.tiles {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 12px; margin: 32px 0 8px;
}
.tile {
  background: var(--surface); border: 1px solid var(--hairline);
  border-radius: 10px; padding: 18px 18px 14px;
}
.tile-label { font-size: 13px; color: var(--ink-2); margin-bottom: 6px; }
.tile-value {
  font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 30px; font-weight: 700; font-variant-numeric: tabular-nums;
  letter-spacing: -0.01em;
}
.tile-unit { font-size: 15px; font-weight: 400; color: var(--ink-2); }
.tile-caption { font-size: 12px; color: var(--ink-3); margin-top: 4px; }
.group { margin-top: 52px; }
h2 {
  font-family: "Archivo", "Helvetica Neue", Arial, sans-serif;
  font-size: 22px; font-weight: 700; letter-spacing: -0.01em; margin: 0 0 6px;
}
.blurb { color: var(--ink-2); max-width: 68ch; margin: 0 0 18px; font-size: 15px; }
.legend { display: flex; gap: 16px; margin-bottom: 10px; }
.legend-item { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--ink-2); }
.swatch { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
.swatch-sync { background: var(--series-sync); }
.swatch-async { background: var(--series-async); }
.swatch-other { background: var(--series-other); }
.chart {
  background: var(--surface); border: 1px solid var(--hairline);
  border-radius: 10px; padding: 18px 18px 12px;
  display: flex; flex-direction: column; gap: 10px;
}
.bar-row { display: grid; grid-template-columns: 180px 1fr 92px; align-items: center; gap: 12px; }
.bar-row:hover .bar { filter: brightness(1.15); }
.bar-label { font-size: 13.5px; color: var(--ink-2); text-align: right; }
.bar-track { position: relative; height: 18px; background: var(--surface-2); border-radius: 4px; }
.bar { position: absolute; left: 0; top: 2px; bottom: 2px; border-radius: 3px; min-width: 2px; }
.bar-sync { background: var(--series-sync); }
.bar-async { background: var(--series-async); }
.bar-other { background: var(--series-other); }
.p95-tick { position: absolute; top: -2px; bottom: -2px; width: 2px; background: var(--tick); opacity: 0.55; }
.bar-value {
  font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px; font-variant-numeric: tabular-nums; text-align: right;
}
.bar-unit { color: var(--ink-3); font-size: 11px; }
.bar-ratio { display: block; color: var(--ink-3); font-size: 11px; }
.headline-wrap { overflow-x: auto; margin: 14px 0 6px; }
table.headline {
  border-collapse: separate; border-spacing: 5px; width: 100%;
  font-size: 15.5px; font-variant-numeric: tabular-nums;
}
table.headline th, table.headline td {
  background: var(--surface); border: none; border-radius: 9px;
  padding: 13px 18px; text-align: left; white-space: nowrap;
  font-family: "Instrument Sans", "Helvetica Neue", Arial, sans-serif;
}
table.headline th {
  font-size: 15.5px; font-weight: 600; color: var(--ink);
  text-transform: none; letter-spacing: 0;
}
table.headline td strong { color: var(--accent); font-weight: 700; }
.cell-ratio { color: var(--ink-3); }
.axis-note { font-size: 12px; color: var(--ink-3); margin: 8px 2px 0; }
.stats { margin-top: 12px; }
.stats summary { cursor: pointer; font-size: 13.5px; color: var(--ink-2); }
.stats summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.table-wrap { overflow-x: auto; margin-top: 10px; }
table { border-collapse: collapse; width: 100%; font-size: 13.5px; }
caption { caption-side: bottom; text-align: left; font-size: 12px; color: var(--ink-3); padding-top: 6px; }
th, td { text-align: left; padding: 7px 12px; border-bottom: 1px solid var(--hairline); }
th { font-size: 12px; letter-spacing: 0.06em; text-transform: uppercase; color: var(--ink-3); font-weight: 600; }
td.num, th.num {
  text-align: right;
  font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  font-variant-numeric: tabular-nums;
}
code { font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12.5px; }
footer { margin-top: 64px; border-top: 1px solid var(--hairline); padding-top: 24px; color: var(--ink-2); font-size: 14px; }
footer code { background: var(--surface); border: 1px solid var(--hairline); border-radius: 5px; padding: 2px 7px; }
footer p { max-width: 72ch; }
.caveat {
  border: 1px solid var(--accent); border-radius: 8px;
  color: var(--ink); background: var(--surface);
  padding: 12px 16px; margin: 20px 0 0; font-size: 14px;
}
@media (max-width: 640px) {
  .bar-row { grid-template-columns: 110px 1fr 80px; }
  .bar-label { font-size: 12px; }
}
"""


def render_page(
    summary: dict, artifact: bool = False, comparison: Optional[dict] = None
) -> str:
    """Render the report body. With artifact=True, emit only page content
    (the Artifact host wraps it in its own document skeleton); otherwise emit
    a complete standalone HTML document. A comparison summary (from
    comparison/run_all.py) adds the cross-framework sections."""
    machine = summary.get("machine", {})
    benchmarks = summary.get("benchmarks", {})

    groups_html = "".join(render_group(group, benchmarks) for group in GROUPS)
    comparison_footer = ""
    if comparison and not comparison.get("quick"):
        cmp_benchmarks = comparison.get("benchmarks", {})
        cmp_groups = comparison_groups(comparison.get("framework_versions") or {})
        groups_html += render_comparison_table(cmp_groups, cmp_benchmarks)
        groups_html += "".join(
            render_group(group, cmp_benchmarks) for group in cmp_groups
        )
        comparison_footer = (
            "<p>Cross-framework sections build the identical agent shape per framework "
            "(one OpenAI model reference, one function tool, telemetry off, no network). "
            "Reproduce with <code>python cookbook/performance/comparison/run_all.py</code> "
            "in an environment holding all four frameworks.</p>"
        )

    head = [
        "<title>Agno Performance</title>",
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<link rel="preconnect" href="https://fonts.googleapis.com">',
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
        "family=Archivo:wght@700;800&family=Instrument+Sans:wght@400;500;600&"
        'family=JetBrains+Mono:wght@400;700&display=swap">',
        "<style>" + CSS + "</style>",
    ]
    body = [
        '<div class="page">',
        "<header>",
        '<div class="eyebrow">Benchmark report</div>',
        "<h1>Agno Performance</h1>",
        '<p class="lede">Framework overhead measured with in-process mock models: no network, no provider, '
        "no API keys. Every number below is what Agno itself costs.</p>",
        render_meta(machine),
        render_caveats(summary),
        render_hero(benchmarks),
        "</header>",
        groups_html,
        "<footer>",
        "<p>Runtime and memory are measured in separate passes; warmup runs are excluded; each benchmark "
        "file runs in a fresh Python process. Import time subtracts interpreter startup; read its median, "
        "sub-millisecond differences are spawn noise. Memory footprint holds 1000 agents alive and reports "
        "the per-agent net allocation delta.</p>",
        comparison_footer,
        "<p>Reproduce with <code>python cookbook/performance/run_all.py</code></p>",
        "</footer>",
        "</div>",
    ]
    if artifact:
        return "\n".join(head + body)
    return "\n".join(
        ["<!doctype html>", '<html lang="en">', "<head>", '<meta charset="utf-8">']
        + head
        + ["</head>", "<body>"]
        + body
        + ["</body>", "</html>"]
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Render benchmark results to an HTML report"
    )
    default_results = Path(__file__).parent / "results" / "summary.json"
    default_comparison = (
        Path(__file__).parent / "results" / "comparison" / "summary.json"
    )
    default_out = Path(__file__).parent / "report" / "agno-performance.html"
    parser.add_argument("--results", type=Path, default=default_results)
    parser.add_argument(
        "--comparison",
        type=Path,
        default=default_comparison,
        help="Cross-framework comparison summary; skipped silently when the file does not exist",
    )
    parser.add_argument("--out", type=Path, default=default_out)
    parser.add_argument(
        "--artifact",
        action="store_true",
        help="Emit page content without the document skeleton, for hosts that provide their own",
    )
    args = parser.parse_args()

    summary = json.loads(args.results.read_text())
    comparison = (
        json.loads(args.comparison.read_text()) if args.comparison.exists() else None
    )
    page = render_page(summary, artifact=args.artifact, comparison=comparison)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(page)
    print("Report written to " + str(args.out))


if __name__ == "__main__":
    main()
