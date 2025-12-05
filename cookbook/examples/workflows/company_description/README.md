# Company Description Workflow

A workflow that generates comprehensive supplier profiles by gathering information from multiple sources and delivers them via email.

## Overview

This workflow combines web crawling, search engines, Wikipedia, and competitor analysis to create detailed supplier profiles. It processes company information through 4 specialized agents running in parallel, then generates a structured markdown report and sends it via email.

The workflow uses workflow session state management to cache analysis results. If the same supplier is analyzed again, it returns cached results instead of re-running the expensive analysis pipeline.

## Getting Started

### Prerequisites
- OpenAI API key
- Resend API key for emails [https://resend.com/api-keys]
- Firecrawl API key for web crawling [https://www.firecrawl.dev/app/api-keys]

### Quick Setup
```bash
export OPENAI_API_KEY="your-openai-key"
export RESEND_API_KEY="your-resend-key"
export FIRECRAWL_API_KEY="your-firecrawl-key"
```

Install dependencies
```
pip install agno openai firecrawl-py resend
```

## Analysis Flow

The workflow processes supplier information through these steps:

```
Company Description Workflow
├── 🔍 Check for Cached Analysis
│   └── If exists → Return Cached Results
├── 🔍 New Analysis Required
│   └── If needed → 
│       ├── 🔄 Parallel Information Gathering
│       │   ├── Web Crawler (Firecrawl)
│       │   ├── Search Engine (DuckDuckGo)
│       │   ├── Wikipedia Research
│       │   └── Competitor Analysis
│       └── 📄 Supplier Profile Generation
│           └── Creates structured markdown report & caches results
└── 📧 Email Delivery
    └── Sends report to specified email
```

The workflow uses workflow session state to intelligently cache analysis results. If the same supplier is analyzed again, it returns cached results instead of re-running the entire analysis pipeline, saving time and API costs. 