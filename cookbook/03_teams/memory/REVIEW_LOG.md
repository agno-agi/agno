# Review Log: memory

> Updated: 2026-02-11

## Framework Issues

(none found)

## Cookbook Quality

[QUALITY] 01_team_with_memory_manager.py — Calls `memory_manager.clear()` at module level (line 27), which clears all memories before every run. Good for demos but should note this is destructive. Uses `uuid4()` for session_id which means no cross-run session continuity unless explicitly set.

[QUALITY] 02_team_with_agentic_memory.py — Clean minimal example. No explicit MemoryManager — just `enable_agentic_memory=True`. Good contrast with 01.

[QUALITY] learning_machine.py — Shows LearningMachine with UserProfileConfig. Uses different session_ids between runs to demonstrate cross-session persistence. However, the model's second response says it has no saved preferences, which may confuse users even though the profile data IS being injected.

## Fixes Applied

(none needed)
