
# OSOP Clinical Triage Workflow

This cookbook demonstrates how an [OSOP](https://github.com/osopcloud/osop-spec) (Open Standard for Orchestration Protocols) workflow definition maps to Agno's agent and workflow primitives.

## What is OSOP?

OSOP is a YAML-based standard for describing multi-step agent workflows in a portable, tool-agnostic format. A single `.osop.yaml` file can be validated, visualized, and implemented across different orchestration frameworks — like OpenAPI, but for agent workflows.

## OSOP to Agno Mapping

| OSOP Concept | Agno Equivalent | Description |
|---|---|---|
| `steps[].agent` | `Agent(...)` | Each OSOP agent maps to an Agno Agent instance |
| `steps[]` | Workflow step | Sequential execution of agents |
| `steps[].conditions` | Conditional branching | Route logic based on previous step output |
| `inputs` | Session state / user input | Data passed into the workflow |
| `outputs` | Final agent response | Structured result from the pipeline |
| `steps[].tools` | `Agent(tools=[...])` | Tools available to each agent |

## Workflow Steps

```
Patient Data --> [Intake Agent] --> [Risk Scoring Agent] --> [Router Agent] --> [Referral Agent]
                                           |
                                           |-- ESI 1-2 --> Emergency Immediate
                                           |-- ESI 3   --> Urgent Care
                                           +-- ESI 4-5 --> Standard Care
```

## Prerequisites

```bash
pip install agno google-genai
export GOOGLE_API_KEY=your-key-here
```

## Run

```bash
python cookbook/osop_clinical_triage/clinical_triage_workflow.py
```

## Files

- `clinical_triage.osop.yaml` - Portable OSOP workflow definition
- `clinical_triage_workflow.py` - Runnable Agno implementation
- `README.md` - This file
