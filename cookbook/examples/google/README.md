# Google Examples

> Showcasing Google-specific AI capabilities with Agno

This directory contains examples demonstrating Google's unique AI features:
- **NanoBanana**: Native image generation using `gemini-2.5-flash-image`
- **Google Grounding**: Real-time web search with source citations
- **URL Context**: Analyze and extract content from web pages
- **Google Search**: Search integration for Gemini 2.0+ models

## Prerequisites

### 1. Install Dependencies

```bash
pip install agno google-genai Pillow
```

### 2. Set Environment Variables

```bash
export GOOGLE_API_KEY=your-api-key
```

## Running Examples

### Run All Agents via AgentOS

```bash
cd cookbook/examples/google
python run.py
```

Visit http://localhost:9000/config to see all available agents.

### Run Individual Examples

```bash
# Image Generation
python creative_studio_agent.py

# Research with Grounding
python research_agent.py

# Product Comparison (URL Context + Search)
python product_comparison_agent.py

# Visual Storytelling
python visual_storyteller_agent.py
```

## Examples Overview

| Example | Agent | Google Features | Memory Features |
|---------|-------|-----------------|-----------------|
| `creative_studio_agent.py` | `creative_studio_agent` | NanoBanana | history |
| `research_agent.py` | `research_agent` | Grounding | user_memories + session_summaries |
| `product_comparison_agent.py` | `product_comparison_agent` | URL Context + Grounding | user_memories + history |
| `visual_storyteller_agent.py` | `visual_storyteller_agent` | NanoBanana | session_summaries + history |

## Database

All agents use SqliteDb for persistence (configured in `db.py`):
```python
from db import demo_db
# Stores to: tmp/google_examples.db
```

## Google-Specific Features

| Feature | Parameter | Description |
|---------|-----------|-------------|
| Google Search | `search=True` | Search the web (Gemini 2.0+) |
| Grounding | `grounding=True` | Search with citations |
| URL Context | `url_context=True` | Analyze web page content |
| NanoBanana | `NanoBananaTools()` | Image generation toolkit |
