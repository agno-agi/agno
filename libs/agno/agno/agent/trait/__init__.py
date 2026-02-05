"""Internal Agent trait modules.

This package contains the internal implementation slices ("traits") that
compose :class:`agno.agent.agent.Agent`.

Traits are **not** part of the public API. Consumers should import
:class:`agno.agent.agent.Agent` (or :class:`agno.agent.Agent`) and treat trait
modules as private implementation details.

Design notes:
- Each trait owns a single concern (init/run/hooks/tools/messages/storage/...).
- ``Agent`` composes traits via multiple inheritance; trait order is intentional
  (Python MRO applies if methods overlap).
- Traits inherit from :class:`agno.agent.trait.base.AgentTraitBase`, which
  provides permissive ``Any``-typed attribute declarations to keep mypy happy
  across the split.
- Prefer ``TYPE_CHECKING`` imports for type-only dependencies to reduce runtime
  imports and avoid circular dependency risks.
"""
