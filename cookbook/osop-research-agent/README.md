# Research Agent Workflow — OSOP Workflow Example

This directory contains a portable [OSOP](https://github.com/osopcloud/osop-spec) workflow definition for a multi-step research agent built with Agno (formerly Phidata).

## What is OSOP?

**OSOP** (Open Standard for Orchestration Protocols) is a YAML-based format for describing multi-step workflows in a tool-agnostic way. It lets you define pipelines, agent workflows, and automation flows that can be understood by any compatible runtime — including Agno, LangChain, CrewAI, and others.

Think of it as the **OpenAPI of workflows**: a single `.osop` file describes what your agent does, so teams can share, review, and port agent workflows across frameworks.

## Workflow Overview

The `phidata-research-agent.osop` file describes a research agent pipeline:

```
User Request → Web Search Agent → Analysis Agent → Report Generator → Deliver Report
```

| Step | OSOP Node Type | Agno Equivalent |
|------|---------------|-----------------|
| User Request | `human` | User input |
| Web Search Agent | `agent` | `Agent` with `DuckDuckGoTools` + `NewspaperTools` |
| Analysis Agent | `agent` | `Agent` with analysis instructions |
| Report Generator | `agent` | `Agent` with report template |
| Deliver Report | `api` | Output / file save |

## Key Features Shown

- **Tool integration**: The web search agent specifies tools (`duckduckgo_search`, `newspaper_reader`) — maps to Agno's tool system
- **Temperature control**: Each agent step has explicit temperature settings for controlling creativity vs. precision
- **Sequential flow**: Clean handoff between specialized agents — maps to Agno's `Workflow` class

## Usage

The `.osop` file is a standalone YAML document. You can:

- **Read it** to understand the agent workflow at a glance
- **Validate it** with the [OSOP CLI](https://github.com/osopcloud/osop): `osop validate phidata-research-agent.osop`
- **Visualize it** with the [OSOP Editor](https://github.com/osopcloud/osop-editor)
- **Use it as a reference** when building the equivalent Agno workflow in Python

## Links

- [OSOP Spec](https://github.com/osopcloud/osop-spec)
- [OSOP CLI](https://github.com/osopcloud/osop)
- [Agno Documentation](https://docs.agno.com/)
