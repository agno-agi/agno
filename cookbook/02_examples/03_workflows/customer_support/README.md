# Customer Support Workflow

A simple customer support system that caches solutions for faster resolution of repeated queries.

## Overview

This workflow demonstrates basic workflow session state management by building a smart customer support system. It caches solutions for customer queries and returns instant responses for exact matches, while generating new solutions for unique problems.

The workflow uses session state to store resolved queries and their solutions for efficient reuse.

## Getting Started

### Prerequisites
- OpenAI API key

### Setup
```bash
export OPENAI_API_KEY="your-openai-key"
```

Install dependencies
```
pip install agno openai
```

Run the workflow
```
python cookbook/examples/workflows_2/customer_support/run_workflow.py
```

## Workflow Flow

The customer support system processes tickets through these simple steps:

```
Customer Support Resolution Pipeline
├── 🔍 Check Cache
│   ├── Look for exact query match in session state
│   └── Return cached solution if found
└── 🔧 Generate New Solution
    ├── Classify the customer query
    ├── Generate step-by-step solution
    └── Cache solution for future use
```

The workflow efficiently caches solutions and learns from each ticket. Exact query matches get resolved instantly from cache, while new queries trigger solution generation and caching.

## Session State Features

**Simple Caching**: Stores query-solution pairs for instant retrieval

**Automatic Learning**: Each new solution is automatically cached for future reuse

**Intelligent Agents**: Uses triage agent for classification and support agent for solution development

## Agents

- **Triage Agent**: Classifies customer queries by category, priority, and tags
- **Support Agent**: Develops clear, step-by-step solutions for customer issues

The workflow demonstrates how session state can be used to build learning systems that improve over time through caching and reuse. 