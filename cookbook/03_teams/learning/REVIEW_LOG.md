# Review Log: learning

> Updated: 2026-02-11

## Framework Issues

(none found — all 6 learning stores work correctly)

## Cookbook Quality

[QUALITY] All learning cookbooks — Excellent progression from simple (`learning=True`) to advanced (DecisionLog with agent tools). Each cookbook demonstrates a unique learning store with clear multi-session flow.

[QUALITY] 01_team_always_learn.py — Duplicate memories accumulate across runs (9 nearly-identical memories about "Alice prefers technical explanations"). The `learning=True` shorthand stores EVERY conversation, so repeated runs create redundant entries. Should note this or add cleanup between runs.

[QUALITY] 05_team_learned_knowledge.py — Good demonstration of the save→search→apply cycle. The team correctly uses `save_learning` and `search_learnings` tools agentically.

[QUALITY] 06_team_decision_log.py — Shows decisions from OTHER previous sessions leaking into the decision log (e.g., "Recommend Python for web scraping" from a prior run). This is expected behavior since the decision store is shared, but could confuse users who run this cookbook multiple times.

## Fixes Applied

(none needed — all cookbooks use correct v2.5 patterns)
