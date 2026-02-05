"""Agent registry helpers.

DB-backed helpers for loading/listing Agents from persisted config/component
registries (e.g., database-backed config stores).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from agno.db.base import BaseDb, ComponentType
from agno.registry.registry import Registry
from agno.utils.log import log_error

if TYPE_CHECKING:
    from agno.agent.agent import Agent


def get_agent_by_id(
    db: BaseDb,
    id: str,
    version: Optional[int] = None,
    label: Optional[str] = None,
    registry: Optional[Registry] = None,
) -> Optional["Agent"]:
    """Get an Agent by id from the database.

    Resolution order:
    - if label is provided: load that labeled version
    - else: load component.current_version

    Args:
        db: Database handle.
        id: Agent entity_id.
        label: Optional label.
        registry: Optional Registry for reconstructing unserializable components.

    Returns:
        Agent instance or None.
    """
    try:
        row = db.get_config(component_id=id, label=label, version=version)
        if row is None:
            return None

        cfg = row.get("config") if isinstance(row, dict) else None
        if cfg is None:
            raise ValueError(f"Invalid config found for agent {id}")

        from agno.agent.agent import Agent

        agent = Agent.from_dict(cfg, registry=registry)
        agent.id = id

        return agent

    except Exception as e:
        log_error(f"Error loading Agent {id} from database: {e}")
        return None


def get_agents(
    db: BaseDb,
    registry: Optional[Registry] = None,
) -> List["Agent"]:
    """Get all agents from the database."""
    from agno.agent.agent import Agent

    agents: List[Agent] = []
    try:
        components, _ = db.list_components(component_type=ComponentType.AGENT)
        for component in components:
            config = db.get_config(component_id=component["component_id"])
            if config is not None:
                agent_config = config.get("config")
                if agent_config is not None:
                    component_id = component["component_id"]
                    if "id" not in agent_config:
                        agent_config["id"] = component_id
                    agent = Agent.from_dict(agent_config, registry=registry)
                    # Ensure agent.id is set to the component_id (the id used to load the agent)
                    # This ensures events use the correct agent_id
                    agent.id = component_id
                    agents.append(agent)
        return agents

    except Exception as e:
        log_error(f"Error loading Agents from database: {e}")
        return []


__all__ = [
    "get_agent_by_id",
    "get_agents",
]

