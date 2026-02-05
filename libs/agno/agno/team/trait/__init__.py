"""Internal Team trait modules.

This package contains internal implementation slices ("traits") that compose
:class:`agno.team.team.Team`.

Traits are **not** part of the public API. Consumers should import
:class:`agno.team.team.Team` (or :class:`agno.team.Team`) and treat trait
modules as private implementation details.

Design notes:
- Each trait owns one concern (init/run/hooks/tools/messages/storage/...).
- ``Team`` composes traits via multiple inheritance; trait order is intentional
  (Python MRO applies if methods overlap).
- Traits inherit from :class:`agno.team.trait.base.TeamTraitBase`, which
  provides permissive ``Any``-typed attribute declarations to keep mypy happy
  across the split.
"""
