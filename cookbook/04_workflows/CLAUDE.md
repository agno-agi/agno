# CLAUDE.md - Workflows Cookbook

Instructions for Claude Code when testing the workflows cookbooks.

---

## Overview

This folder contains **workflow patterns** - multi-step pipelines that orchestrate agents, teams, and functions in sequence, parallel, conditional, or looping patterns.

**Total Examples:** 129
**Structure:** Deeply nested by pattern type (sync/async variants)

---

## Quick Reference

**Test Environment:**
```bash
.venvs/demo/bin/python
```

**Run a cookbook:**
```bash
.venvs/demo/bin/python cookbook/04_workflows/_01_basic_workflows/_01_sequence_of_steps/sync/sequence_of_steps.py
```

---

## Folder Structure

| Folder | Description |
|:-------|:------------|
| `_01_basic_workflows/` | Sequence of steps, function steps |
| `_02_workflows_conditional_execution/` | If/else branching |
| `_03_workflows_loop_execution/` | Loop patterns |
| `_04_workflows_parallel_execution/` | Parallel step execution |
| `_05_workflows_conditional_branching/` | Router/selector patterns |
| `_06_advanced_concepts/` | Structured I/O, early stopping, session state |

Each folder has `sync/` and `async/` subfolders with equivalent examples.

---

## Key Patterns

### Sequence
Steps run one after another, passing data between them.

### Conditional
Steps run based on evaluator function results.

### Loop
Steps repeat until a condition is met.

### Parallel
Multiple steps run concurrently.

### Router
Dynamic step selection based on input.

---

## Testing Priorities

### High Priority
- `_01_basic_workflows/` - Core patterns
- `_06_advanced_concepts/_04_shared_session_state/` - State management

### Medium Priority
- `_04_workflows_parallel_execution/` - Performance patterns
- `_05_workflows_conditional_branching/` - Dynamic routing

---

## API Keys Required

- `OPENAI_API_KEY` - Most examples

---

## Known Issues

1. Debug warning about "no running event loop" may appear but doesn't affect execution
2. Streaming variants require careful event handling
3. Early stopping patterns need proper cleanup
