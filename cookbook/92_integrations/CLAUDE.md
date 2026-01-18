# CLAUDE.md - Integrations Cookbook

Instructions for Claude Code when testing the integrations cookbooks.

---

## Overview

This folder contains **third-party integration** examples - observability platforms, memory services, and messaging platforms.

**Total Examples:** 37
**Organization:** By integration type

---

## Quick Reference

**Test Environment:**
```bash
.venvs/demo/bin/python
```

**Run a cookbook:**
```bash
.venvs/demo/bin/python cookbook/91_integrations/observability/langfuse_via_openinference.py
```

---

## Folder Structure

| Folder | Description |
|:-------|:------------|
| `a2a/` | Agent-to-agent protocol |
| `discord/` | Discord bot integration |
| `memory/` | External memory services |
| `observability/` | Tracing platforms |

---

## Observability Platforms

| Platform | File |
|:---------|:-----|
| AgentOps | `agent_ops.py` |
| Arize Phoenix | `arize_phoenix_*.py` |
| Langfuse | `langfuse_*.py` |
| LangSmith | `langsmith_*.py` |
| Langtrace | `langtrace_op.py` |
| LangWatch | `langwatch_op.py` |
| Logfire | `logfire_*.py` |
| Opik | `opik_*.py` |
| Traceloop | `traceloop_op.py` |
| Weave | `weave_op.py` |
| Maxim | `maxim_ops.py` |
| Atla | `atla_op.py` |

---

## Memory Services

| Service | File |
|:--------|:-----|
| Mem0 | `mem0_integration.py` |
| Memori | `memori_integration.py` |
| Zep | `zep_integration.py` |

---

## Messaging

| Platform | Files |
|:---------|:------|
| Discord | `basic.py`, `agent_with_media.py`, `agent_with_user_memory.py` |

---

## Testing Priorities

### High Priority
- `observability/langfuse_via_openinference.py` - Popular choice
- `discord/basic.py` - Discord integration

### Notes
- Most observability integrations require API keys
- Discord requires bot token and permissions
