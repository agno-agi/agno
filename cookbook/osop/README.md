# OSOP Workflow Example — Content Pipeline

This directory contains a portable [OSOP](https://github.com/osop-org/osop-spec) (Open Standard for Orchestration Protocols)
workflow definition demonstrating Agno agent patterns, plus a runnable Agno implementation of the same pipeline.

## What is OSOP?

OSOP is a YAML-based standard for describing multi-step agent workflows in a tool-agnostic way — like OpenAPI, but for
workflows. A single `.osop` file can be validated, visualized, and used as a portable reference across orchestration
frameworks (Agno, LangChain, CrewAI, and others).

## Workflow Overview

The `content-pipeline.osop` file describes a content creation pipeline:

```
User Request → Research Agent → Content Planner → Writer Agent → Reviewer Agent → Publish Content
```

| Step | OSOP Node Type | Agno Equivalent |
|------|---------------|-----------------|
| User Request | `human` | Workflow input |
| Research Agent | `agent` | `Agent` with `WebSearchTools` |
| Content Planner | `agent` | `Agent` with planning instructions |
| Content Writer | `agent` | `Agent` with writing instructions |
| Reviewer Agent | `agent` | `Agent` with review instructions |
| Publish Content | `api` | Workflow output / file save |

`content_pipeline.py` implements the same pipeline as an Agno `Workflow` with sequential `Step`s, including input-preparation
functions that pass research findings and outlines between steps.

## Key Features Shown

- **Tool integration**: the research step declares `web_search` — maps to Agno's `WebSearchTools`
- **Temperature control**: each agent step has an explicit temperature for creativity vs. precision
- **Sequential flow**: clean handoffs between specialized agents — maps to Agno's `Workflow` class
- **Cross-framework portability**: the `.osop` file describes intent, not framework APIs

## Usage

Run the Agno implementation (requires `OPENAI_API_KEY`):

```bash
.venvs/demo/bin/python cookbook/osop/content_pipeline.py
```

The `.osop` file is a standalone YAML document — read it to understand the pipeline at a glance, or use it as a reference
when porting the workflow to another framework.

## Note on prior work

PR #7290 proposed an OSOP research-agent example for this issue but is stale and unmerged, and its YAML had broken
indentation plus pre-rename `phidata` naming. This contribution supersedes that approach with a corrected, valid YAML
document, current Agno naming and model conventions, and a runnable Python implementation of the same pipeline.

## Links

- [Agno Documentation](https://docs.agno.com)
- [Agno Workflows](https://docs.agno.com/workflows)
