# CLAUDE.md - Evals Cookbook

Instructions for Claude Code when testing the evals cookbooks.

---

## Overview

This folder contains **evaluation** examples - how to measure agent accuracy, reliability, and performance.

**Total Examples:** 50
**Organization:** By eval type

---

## Quick Reference

**Test Environment:**
```bash
.venvs/demo/bin/python
```

**Run a cookbook:**
```bash
.venvs/demo/bin/python cookbook/12_evals/accuracy/accuracy_basic.py
```

---

## Folder Structure

| Folder | Description |
|:-------|:------------|
| `accuracy/` | Answer correctness evals |
| `agent_as_judge/` | LLM-based evaluation |
| `performance/` | Speed and cost metrics |
| `reliability/` | Tool calling reliability |

---

## Eval Types

### Accuracy
Compare agent answers against expected results.

### Agent as Judge
Use another LLM to evaluate responses.
- Binary (pass/fail)
- Scored (1-10)
- Custom criteria

### Performance
Measure:
- Instantiation time
- Response latency
- Token usage
- Memory overhead

### Reliability
Measure tool calling success rate.

---

## Performance Comparisons

The `performance/comparison/` folder compares Agno against:
- AutoGen
- CrewAI
- LangGraph
- OpenAI Agents
- Pydantic AI
- SmolaAgents

---

## Testing Priorities

### High Priority
- `accuracy/accuracy_basic.py`
- `agent_as_judge/agent_as_judge_basic.py`
- `performance/instantiate_agent.py`

---

## Notes

- Evals may have variable results due to LLM non-determinism
- Performance tests should be run multiple times
- Agent-as-judge requires additional API calls
