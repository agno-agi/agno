# CLAUDE.md - Teams Cookbook

Instructions for Claude Code when testing the teams cookbooks.

---

## Overview

This folder contains **feature documentation** for multi-agent teams - groups of agents that collaborate to solve tasks.

**Total Examples:** 120
**Subfolders:** 20

---

## Quick Reference

**Test Environment:**
```bash
.venvs/demo/bin/python
./cookbook/scripts/run_pgvector.sh  # For knowledge/memory examples
```

**Run a cookbook:**
```bash
.venvs/demo/bin/python cookbook/04_teams/<subfolder>/<file>.py
```

---

## Folder Structure

| Folder | Count | Description |
|:-------|------:|:------------|
| `async_flows/` | 5 | Async team execution |
| `basic_flows/` | 9 | Basic coordination patterns |
| `context_compression/` | 3 | Tool call compression |
| `context_management/` | 2 | Context filtering |
| `dependencies/` | 6 | Runtime dependency injection |
| `distributed_rag/` | 4 | Distributed RAG |
| `guardrails/` | 4 | PII, moderation, injection |
| `hooks/` | 6 | Pre/post hooks |
| `knowledge/` | 5 | Shared knowledge bases |
| `memory/` | 3 | Memory management |
| `metrics/` | 2 | Performance monitoring |
| `multimodal/` | 9 | Image, audio, video |
| `other/` | 12 | CLI, retries, cancellation |
| `reasoning/` | 3 | Multi-agent reasoning |
| `search_coordination/` | 4 | Coordinated search |
| `session/` | 13 | Session management |
| `state/` | 8 | Shared state |
| `streaming/` | 5 | Real-time streaming |
| `structured_input_output/` | 10 | Pydantic schemas |
| `tools/` | 5 | Tool coordination |

---

## Testing Priorities

### High Priority
- `basic_flows/` - Core team patterns
- `state/` - Shared state management
- `streaming/` - Event handling

### Medium Priority
- `knowledge/` - RAG with teams
- `memory/` - Persistent memory
- `hooks/` - Production patterns

---

## API Keys Required

- `OPENAI_API_KEY` - Most examples
- `GOOGLE_API_KEY` - Multimodal examples

---

## Known Issues

1. Team model inherits to members by default
2. Share member interactions requires explicit flag
3. Multimodal requires local media files
