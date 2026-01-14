# CLAUDE.md - Agents Cookbook

Instructions for Claude Code when testing the agents feature cookbook.

---

## Overview

This folder contains **feature documentation examples** - small, focused examples that demonstrate specific agent capabilities. Unlike `02_examples/` which has use-case-focused agents, this folder is organized by **feature**.

**Total Examples:** 165+
**Subfolders:** 19

---

## Quick Reference

**Test Environment:**
```bash
# Virtual environment with all dependencies
.venvs/demo/bin/python

# Start PostgreSQL with PgVector (for RAG/knowledge examples)
./cookbook/scripts/run_pgvector.sh
```

**Run a cookbook:**
```bash
.venvs/demo/bin/python cookbook/03_agents/<subfolder>/<file>.py
```

**Test results file:**
```
cookbook/03_agents/TEST_LOG.md
```

---

## Folder Structure

| Folder | Count | Description |
|:-------|------:|:------------|
| `agentic_search/` | 5 | RAG with reasoning, reranking |
| `async/` | 10 | Async patterns, concurrent execution |
| `caching/` | 5 | Model response caching |
| `context_compression/` | 4 | Tool call compression |
| `context_management/` | 9 | Instructions, few-shot learning |
| `culture/` | 6 | Shared collective learning (impressive!) |
| `custom_logging/` | 4 | Logging configuration |
| `dependencies/` | 6 | Dependency injection patterns |
| `events/` | 3 | Event handling during streaming |
| `guardrails/` | 3 | PII detection, prompt injection |
| `hooks/` | 7 | Pre/post hooks for validation |
| `human_in_the_loop/` | 22 | Confirmation, user input |
| `input_and_output/` | 17 | Input/output schemas |
| `multimodal/` | 21 | Image, audio, video processing |
| `other/` | 15 | Metrics, retries, cancellation |
| `rag/` | 9 | Traditional and agentic RAG |
| `session/` | 14 | Session management |
| `skills/` | 2 | Agent skills system |
| `state/` | 13 | Session state management |

---

## Testing Priorities

### High Priority (Impressive Features)

| Folder | Key Files | Why Important |
|:-------|:----------|:--------------|
| `culture/` | All 5 files | Unique shared learning feature |
| `hooks/` | `output_stream_hook_send_notification.py` | Production-ready pattern |
| `agentic_search/` | `agentic_rag_with_reasoning.py` | Advanced RAG |
| `state/` | `session_state_basic.py` | Core feature |
| `multimodal/` | `video_caption_agent.py` | Impressive capability |
| `other/` | `cancel_a_run.py` | Production feature |

### Medium Priority (Common Patterns)

| Folder | Focus |
|:-------|:------|
| `human_in_the_loop/` | Confirmation and input patterns |
| `async/` | Performance patterns |
| `input_and_output/` | Schema patterns |
| `guardrails/` | Security patterns |

### Lower Priority (Advanced/Niche)

| Folder | Focus |
|:-------|:------|
| `caching/` | Performance optimization |
| `context_compression/` | Context management |
| `dependencies/` | Dependency injection |
| `custom_logging/` | Logging setup |

---

## Testing Workflow

### 1. Before Testing

**API Keys Required:**
- `OPENAI_API_KEY` - Most examples
- `ANTHROPIC_API_KEY` - Culture examples, some RAG
- `GOOGLE_API_KEY` - Multimodal examples
- `CO_API_KEY` - Cohere embedder/reranker

**Services Required:**
- PostgreSQL with PgVector for RAG examples
- Some multimodal examples need local files (images/videos)

### 2. Running Tests

```bash
# Basic test
.venvs/demo/bin/python cookbook/03_agents/state/session_state_basic.py

# Culture examples (run in sequence)
.venvs/demo/bin/python cookbook/03_agents/culture/01_create_cultural_knowledge.py
.venvs/demo/bin/python cookbook/03_agents/culture/02_use_cultural_knowledge_in_agent.py
```

### 3. Updating TEST_LOG.md

Document results in `cookbook/03_agents/TEST_LOG.md`.

---

## Highlighted Features

### Culture System (Unique!)

The `culture/` folder demonstrates Agno's unique shared learning system where agents can:
- Create and share cultural knowledge
- Automatically update shared knowledge
- Apply consistent tone and reasoning

This is a v0.1 feature and highly differentiating.

### Hooks System

The `hooks/` folder shows pre/post hooks for:
- Input validation and transformation
- Output validation and formatting
- Sending notifications after responses
- Session state management

### Human-in-the-Loop

The `human_in_the_loop/` folder is comprehensive with 22 examples covering:
- Confirmation required patterns
- User input collection
- External tool execution
- Async and streaming variants

### Run Cancellation

The `other/cancel_a_run.py` shows production-ready patterns for:
- Starting runs in separate threads
- Cancelling runs mid-execution
- Handling cancellation events
- Redis-based distributed cancellation

---

## Known Issues

1. **Multimodal examples need local files** - Many require sample images/videos in the folder
2. **Culture examples should run in sequence** - Start with 01, then 02, etc.
3. **RAG examples need PgVector or LanceDb** - Start the appropriate service first
4. **Video examples need ffmpeg** - Install with `brew install ffmpeg`

---

## Subfolder READMEs

Some subfolders have their own documentation:
- `culture/README.md` - Detailed explanation of culture system
- `dependencies/README.md` - Dependency injection patterns
- `agentic_search/lightrag/readme.md` - LightRAG integration

---

## Notes

This folder is well-organized and comprehensive. The README.md already provides good documentation. Focus testing on:
1. The unique features (culture, hooks, cancellation)
2. Core patterns (state, human-in-the-loop)
3. Advanced features (multimodal, agentic RAG)
