# REVIEW_LOG.md - 93 Components Cookbook

**Review Date:** 2026-02-11
**Reviewer:** Codex 5.3 + Opus 4.6
**Branch:** `cookbooks/v2.5-testing`

---

## Framework Issues

[FRAMEWORK] `libs/agno/agno/workflow/workflow.py:795` — `Workflow.save()` recursively walks `Condition.steps` but does not persist the Condition's `evaluator` function reference in the link/step metadata. The evaluator is only restored if it was serialized by `Condition.to_dict()` (which stores `evaluator_ref` by `__name__`), but the save walk doesn't explicitly verify this is captured.

[FRAMEWORK] `libs/agno/agno/workflow/step.py:176` — `Step.from_dict()` only restores `team_id` when a `registry` is present. If no registry is passed, any Step with a team reference silently loses it during deserialization.

[FRAMEWORK] `libs/agno/agno/db/postgres/postgres.py:177` — `PostgresDb.from_dict()` does not round-trip newer init fields added in v2.5 (e.g., `approvals_table`, `schedules_table`). These fields are lost during serialization/deserialization.

[FRAMEWORK] `libs/agno/agno/workflow/workflow.py:5120` — `get_workflows()` does not fetch/pass version links (unlike `get_workflow_by_id()` which fetches links at line 5089). This means batch-loaded workflows cannot restore agent/team references from links.

---

## Cookbook Quality

[QUALITY] `save_agent.py` — Uses old import `from agno.agent.agent import Agent` instead of v2.5 canonical `from agno.agent import Agent`. Works but non-idiomatic.

[QUALITY] `get_agent.py` — Same old import style for `get_agent_by_id`, `get_agents`.

[QUALITY] `registry.py` — Main teaching goal (rehydration from DB) is not demonstrated; the `get_agent_by_id(registry=registry)` call is commented out. The example only saves, making the Registry usage unclear for learners.

[QUALITY] `get_team.py` — Uses `from agno.team.team import` instead of `from agno.team import`.

[QUALITY] `agent_os_registry.py` — Uses old import `from agno.agent.agent import Agent`.

[QUALITY] `demo.py` — Good breadth demo but references model IDs (`gpt-5-mini`, `gpt-5`) that may confuse users about which models are available.

---

## Fixes Applied

None — all cookbooks are backward-compatible with v2.5. Old imports still work via `__init__.py` re-exports.
