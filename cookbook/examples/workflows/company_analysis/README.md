# Company Analysis Workflow

A Company analysis workflow that uses strategic frameworks to evaluate suppliers and generate business intelligence reports.

## Overview

This workflow analyzes companies using 8 specialized agents that perform research across multiple strategic frameworks including PESTLE, Porter's Five Forces, and Kraljic Matrix. It generates comprehensive supplier analysis reports for procurement decision-making.

## Getting Started

### Prerequisites
- OpenAI API key
- Firecrawl API. You can get one from https://www.firecrawl.dev/app/api-keys

### Setup
```bash
export OPENAI_API_KEY="your-openai-key"
export FIRECRAWL_API_KEY="your-firecrawl-key"
```

Install dependencies

```
pip install agno firecrawl-py openai
```

Run the workflow

```
python cookbook/examples/workflows_2/company_analysis/run_workflow.py
```

## Analysis Flow

The workflow analyzes companies through strategic frameworks:

```
Company Analysis Workflow
├── Company Overview Research
├── Parallel Strategic Analysis
│   ├── Switching Barriers Analysis
│   ├── PESTLE Analysis
│   ├── Porter's Five Forces Analysis
│   ├── Kraljic Matrix Analysis
│   ├── Cost Drivers Analysis
│   └── Alternative Suppliers Research
└── Report Compilation
```

The workflow uses 8 specialized agents running in parallel to perform comprehensive strategic analysis across multiple frameworks, then compiles the results into an executive-ready procurement report. 