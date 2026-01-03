"""
Entity Memory Store
===================
Stores facts about third-party entities (companies, projects, people, systems).

Like UserProfile but for things that aren't the user. Each entity has:
- Core properties (name, description, key-value properties)
- Facts (semantic memory - timeless facts)
- Events (episodic memory - time-bound occurrences)
- Relationships (graph edges to other entities)

## Namespace (Sharing Boundary)

Entities can be private or shared:
- namespace="user": Private per user (default)
- namespace="team": Shared within team_id
- namespace="global": Shared with everyone
- namespace="sales_west": Custom grouping

## Usage

    # Configure
    entity_config = EntityMemoryConfig(
        db=db,
        model=model,
        namespace="team",  # Shared within team
        enable_agent_tools=True,
    )

    # In LearningMachine
    learning = LearningMachine(
        db=db,
        model=model,
        entity_memory=entity_config,
    )

    # Agent can now use: search_entities, add_entity_fact, etc.
"""

import inspect
import json
import logging
import uuid
from dataclasses import fields
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Union

from agno.learn.config import EntityMemoryConfig, LearningMode
from agno.learn.protocol import LearningStore
from agno.learn.schemas import EntityMemory
from agno.learn.utils import format_messages_for_prompt

logger = logging.getLogger(__name__)


class EntityMemoryStore(LearningStore):
    """Store for third-party entity facts.

    Implements the LearningStore protocol for entity memory.
    """

    def __init__(self, config: EntityMemoryConfig):
        """Initialize the entity memory store.

        Args:
            config: EntityMemoryConfig with db, model, and settings.
        """
        self.config = config
        self.db = config.db
        self.model = config.model
        self.schema = config.schema or EntityMemory

    # =========================================================================
    # Namespace Resolution
    # =========================================================================

    def _resolve_namespace(
        self,
        user_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> str:
        """Resolve the namespace based on config and runtime context.

        Args:
            user_id: Current user ID.
            team_id: Current team ID.

        Returns:
            Resolved namespace string.
        """
        ns = self.config.namespace

        if ns == "user":
            return user_id or "__no_user__"
        elif ns == "team":
            return team_id or "__no_team__"
        elif ns == "global":
            return "__global__"
        else:
            # Custom namespace string
            return ns

    # =========================================================================
    # Core Operations
    # =========================================================================

    def get(
        self,
        entity_id: str,
        user_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> Optional[EntityMemory]:
        """Get an entity by ID.

        Args:
            entity_id: The entity's unique identifier.
            user_id: Current user (for namespace resolution).
            team_id: Current team (for namespace resolution).

        Returns:
            EntityMemory if found, None otherwise.
        """
        if not self.db or not entity_id:
            return None

        namespace = self._resolve_namespace(user_id, team_id)

        try:
            row = self.db.get_learning(
                learning_type="entity_memory",
                entity_id=entity_id,
                namespace=namespace,
            )

            if row and row.get("content"):
                return self.schema.from_dict(row["content"])

            return None

        except Exception as e:
            logger.warning(f"Error getting entity {entity_id}: {e}")
            return None

    def search(
        self,
        query: str,
        user_id: Optional[str] = None,
        team_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        limit: int = 10,
        **kwargs,
    ) -> List[EntityMemory]:
        """Search entities by query.

        Args:
            query: Search query (searches name, description, facts).
            user_id: Current user (for namespace resolution).
            team_id: Current team (for namespace resolution).
            entity_type: Filter by entity type (optional).
            limit: Maximum results to return.

        Returns:
            List of matching EntityMemory objects.
        """
        if not self.db or not query:
            return []

        namespace = self._resolve_namespace(user_id, team_id)

        try:
            rows = self.db.search_learnings(
                learning_type="entity_memory",
                namespace=namespace,
                query=query,
                entity_type=entity_type,
                limit=limit,
            )

            results = []
            for row in rows:
                if row.get("content"):
                    entity = self.schema.from_dict(row["content"])
                    if entity:
                        results.append(entity)

            return results

        except Exception as e:
            logger.warning(f"Error searching entities: {e}")
            return []

    def list_entities(
        self,
        user_id: Optional[str] = None,
        team_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        limit: int = 100,
        **kwargs,
    ) -> List[EntityMemory]:
        """List all entities in namespace.

        Args:
            user_id: Current user (for namespace resolution).
            team_id: Current team (for namespace resolution).
            entity_type: Filter by entity type (optional).
            limit: Maximum results to return.

        Returns:
            List of EntityMemory objects.
        """
        if not self.db:
            return []

        namespace = self._resolve_namespace(user_id, team_id)

        try:
            rows = self.db.list_learnings(
                learning_type="entity_memory",
                namespace=namespace,
                entity_type=entity_type,
                limit=limit,
            )

            results = []
            for row in rows:
                if row.get("content"):
                    entity = self.schema.from_dict(row["content"])
                    if entity:
                        results.append(entity)

            return results

        except Exception as e:
            logger.warning(f"Error listing entities: {e}")
            return []

    def save(
        self,
        entity: EntityMemory,
        user_id: Optional[str] = None,
        team_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        **kwargs,
    ) -> bool:
        """Save an entity.

        Args:
            entity: The EntityMemory to save.
            user_id: Current user (for namespace resolution).
            team_id: Current team (for namespace resolution).
            agent_id: Which agent is saving.

        Returns:
            True if saved successfully, False otherwise.
        """
        if not self.db or not entity:
            return False

        namespace = self._resolve_namespace(user_id, team_id)

        try:
            now = datetime.now(timezone.utc).isoformat()

            # Update metadata
            entity.namespace = namespace
            entity.user_id = user_id
            entity.team_id = team_id
            entity.agent_id = agent_id
            entity.updated_at = now

            if not entity.created_at:
                entity.created_at = now

            self.db.upsert_learning(
                learning_type="entity_memory",
                entity_id=entity.entity_id,
                namespace=namespace,
                content=entity.to_dict(),
                user_id=user_id,
                team_id=team_id,
                agent_id=agent_id,
            )

            return True

        except Exception as e:
            logger.error(f"Error saving entity {entity.entity_id}: {e}")
            return False

    def delete(
        self,
        entity_id: str,
        user_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> bool:
        """Delete an entity.

        Args:
            entity_id: The entity's unique identifier.
            user_id: Current user (for namespace resolution).
            team_id: Current team (for namespace resolution).

        Returns:
            True if deleted successfully, False otherwise.
        """
        if not self.db or not entity_id:
            return False

        namespace = self._resolve_namespace(user_id, team_id)

        try:
            self.db.delete_learning(
                learning_type="entity_memory",
                entity_id=entity_id,
                namespace=namespace,
            )
            return True

        except Exception as e:
            logger.error(f"Error deleting entity {entity_id}: {e}")
            return False

    # =========================================================================
    # Fact/Event/Relationship Operations
    # =========================================================================

    def add_fact(
        self,
        entity_id: str,
        fact: str,
        user_id: Optional[str] = None,
        team_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        **kwargs,
    ) -> Optional[str]:
        """Add a fact to an entity.

        Creates the entity if it doesn't exist.

        Args:
            entity_id: The entity's unique identifier.
            fact: The fact text.
            user_id: Current user.
            team_id: Current team.
            agent_id: Which agent is adding.
            **kwargs: Additional fact metadata.

        Returns:
            Fact ID if added successfully, None otherwise.
        """
        if not entity_id or not fact:
            return None

        entity = self.get(entity_id, user_id, team_id)

        if not entity:
            # Create new entity with unknown type
            entity = self.schema(
                entity_id=entity_id,
                entity_type="unknown",
            )

        fact_id = entity.add_fact(fact, **kwargs)
        self.save(entity, user_id, team_id, agent_id)

        return fact_id

    def add_event(
        self,
        entity_id: str,
        event: str,
        date: Optional[str] = None,
        user_id: Optional[str] = None,
        team_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        **kwargs,
    ) -> Optional[str]:
        """Add an event to an entity.

        Creates the entity if it doesn't exist.

        Args:
            entity_id: The entity's unique identifier.
            event: The event description.
            date: When the event occurred.
            user_id: Current user.
            team_id: Current team.
            agent_id: Which agent is adding.

        Returns:
            Event ID if added successfully, None otherwise.
        """
        if not entity_id or not event:
            return None

        entity = self.get(entity_id, user_id, team_id)

        if not entity:
            entity = self.schema(
                entity_id=entity_id,
                entity_type="unknown",
            )

        event_id = entity.add_event(event, date, **kwargs)
        self.save(entity, user_id, team_id, agent_id)

        return event_id

    def add_relationship(
        self,
        entity_id: str,
        related_entity_id: str,
        relation: str,
        user_id: Optional[str] = None,
        team_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        **kwargs,
    ) -> Optional[str]:
        """Add a relationship between entities.

        Creates both entities if they don't exist.

        Args:
            entity_id: The source entity's ID.
            related_entity_id: The target entity's ID.
            relation: The relationship type.
            user_id: Current user.
            team_id: Current team.
            agent_id: Which agent is adding.

        Returns:
            Relationship ID if added successfully, None otherwise.
        """
        if not entity_id or not related_entity_id or not relation:
            return None

        entity = self.get(entity_id, user_id, team_id)

        if not entity:
            entity = self.schema(
                entity_id=entity_id,
                entity_type="unknown",
            )

        rel_id = entity.add_relationship(related_entity_id, relation, **kwargs)
        self.save(entity, user_id, team_id, agent_id)

        return rel_id

    # =========================================================================
    # LearningStore Protocol
    # =========================================================================

    def build_context(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        team_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        **kwargs,
    ) -> Optional[str]:
        """Build context string for agent prompts.

        Returns a summary of known entities for this namespace.
        """
        entities = self.list_entities(user_id, team_id, limit=20)

        if not entities:
            return None

        parts = ["## Known Entities\n"]

        for entity in entities:
            parts.append(f"- **{entity.name or entity.entity_id}** ({entity.entity_type})")
            if entity.description:
                parts.append(f"  {entity.description}")

        return "\n".join(parts)

    def get_tools(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        team_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        **kwargs,
    ) -> List[Callable]:
        """Get agent tools for entity memory.

        Returns tools based on config settings.
        """
        if not self.config.enable_agent_tools:
            return []

        tools = []

        if self.config.agent_can_search_entities:
            tools.append(self._build_search_entities_tool(user_id, team_id, agent_id))

        if self.config.agent_can_create_entity:
            tools.append(self._build_create_entity_tool(user_id, team_id, agent_id))
            tools.append(self._build_add_entity_fact_tool(user_id, team_id, agent_id))
            tools.append(self._build_add_entity_event_tool(user_id, team_id, agent_id))
            tools.append(self._build_add_entity_relationship_tool(user_id, team_id, agent_id))

        if self.config.agent_can_update_entity:
            tools.append(self._build_update_entity_tool(user_id, team_id, agent_id))

        return tools

    def get_system_message(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        team_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        **kwargs,
    ) -> Optional[str]:
        """Get system message explaining entity memory tools."""
        if not self.config.enable_agent_tools:
            return None

        return """## Entity Memory

You have access to an entity memory system for tracking facts about third-party
entities (companies, projects, people, systems, products).

### Tools Available

- **search_entities**: Find entities by name or description
- **create_entity**: Create a new entity with type, name, description
- **add_entity_fact**: Add a fact to an entity (creates if needed)
- **add_entity_event**: Add a time-bound event to an entity
- **add_entity_relationship**: Add a relationship between entities
- **update_entity**: Update an entity's properties

### Guidelines

- Use consistent entity_ids (lowercase, underscores: "acme_corp", "john_smith")
- Search before creating to avoid duplicates
- Facts are timeless truths ("Uses PostgreSQL")
- Events are time-bound ("Launched v2 on Jan 15")
- Relationships connect entities ("Bob is CEO of Acme")
"""

    async def extract_and_save(
        self,
        messages: List[Any],
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        team_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Extract entities from conversation and save them.

        Only runs if mode is BACKGROUND.
        """
        if self.config.mode != LearningMode.BACKGROUND:
            return

        if not self.model or not messages:
            return

        try:
            # Get existing entities for context
            existing = self.list_entities(user_id, team_id, limit=50)
            existing_context = self._format_existing_entities(existing)

            # Build extraction prompt
            system_message = self._get_extraction_system_message(existing_context)
            conversation = format_messages_for_prompt(messages)

            # Get tools for extraction
            extraction_tools = self._get_extraction_tools(user_id, team_id, agent_id)

            # Run extraction
            response = await self.model.aresponse(
                messages=[{"role": "user", "content": conversation}],
                system=system_message,
                tools=extraction_tools,
            )

            # Process tool calls from response
            if hasattr(response, "tool_calls") and response.tool_calls:
                for tool_call in response.tool_calls:
                    await self._execute_extraction_tool(
                        tool_call,
                        user_id,
                        team_id,
                        agent_id,
                    )

        except Exception as e:
            logger.error(f"Error extracting entities: {e}")

    # =========================================================================
    # Tool Builders
    # =========================================================================

    def _build_search_entities_tool(
        self,
        user_id: Optional[str],
        team_id: Optional[str],
        agent_id: Optional[str],
    ) -> Callable:
        """Build the search_entities tool."""

        def search_entities(query: str, entity_type: Optional[str] = None) -> str:
            """Search for entities by name, description, or facts.

            Args:
                query: Search query.
                entity_type: Filter by type (company, project, person, etc).

            Returns:
                JSON list of matching entities.
            """
            results = self.search(
                query=query,
                user_id=user_id,
                team_id=team_id,
                entity_type=entity_type,
                limit=10,
            )

            if not results:
                return json.dumps({"entities": [], "message": "No entities found"})

            return json.dumps({
                "entities": [
                    {
                        "entity_id": e.entity_id,
                        "entity_type": e.entity_type,
                        "name": e.name,
                        "description": e.description,
                        "fact_count": len(e.facts),
                    }
                    for e in results
                ]
            })

        return search_entities

    def _build_create_entity_tool(
        self,
        user_id: Optional[str],
        team_id: Optional[str],
        agent_id: Optional[str],
    ) -> Callable:
        """Build the create_entity tool."""

        def create_entity(
            entity_id: str,
            entity_type: str,
            name: str,
            description: Optional[str] = None,
        ) -> str:
            """Create a new entity.

            Args:
                entity_id: Unique identifier (lowercase, underscores).
                entity_type: Type: company, project, person, system, product.
                name: Display name.
                description: Brief description.

            Returns:
                Confirmation message.
            """
            # Check if exists
            existing = self.get(entity_id, user_id, team_id)
            if existing:
                return json.dumps({
                    "success": False,
                    "error": f"Entity {entity_id} already exists",
                })

            entity = self.schema(
                entity_id=entity_id,
                entity_type=entity_type,
                name=name,
                description=description,
            )

            success = self.save(entity, user_id, team_id, agent_id)

            return json.dumps({
                "success": success,
                "entity_id": entity_id,
            })

        return create_entity

    def _build_add_entity_fact_tool(
        self,
        user_id: Optional[str],
        team_id: Optional[str],
        agent_id: Optional[str],
    ) -> Callable:
        """Build the add_entity_fact tool."""

        def add_entity_fact(entity_id: str, fact: str) -> str:
            """Add a fact to an entity. Creates entity if needed.

            Args:
                entity_id: The entity's unique identifier.
                fact: The fact to add (e.g., "Uses PostgreSQL").

            Returns:
                Confirmation with fact ID.
            """
            fact_id = self.add_fact(
                entity_id=entity_id,
                fact=fact,
                user_id=user_id,
                team_id=team_id,
                agent_id=agent_id,
            )

            return json.dumps({
                "success": fact_id is not None,
                "fact_id": fact_id,
                "entity_id": entity_id,
            })

        return add_entity_fact

    def _build_add_entity_event_tool(
        self,
        user_id: Optional[str],
        team_id: Optional[str],
        agent_id: Optional[str],
    ) -> Callable:
        """Build the add_entity_event tool."""

        def add_entity_event(
            entity_id: str,
            event: str,
            date: Optional[str] = None,
        ) -> str:
            """Add a time-bound event to an entity.

            Args:
                entity_id: The entity's unique identifier.
                event: The event description.
                date: When it occurred (ISO format or natural language).

            Returns:
                Confirmation with event ID.
            """
            event_id = self.add_event(
                entity_id=entity_id,
                event=event,
                date=date,
                user_id=user_id,
                team_id=team_id,
                agent_id=agent_id,
            )

            return json.dumps({
                "success": event_id is not None,
                "event_id": event_id,
                "entity_id": entity_id,
            })

        return add_entity_event

    def _build_add_entity_relationship_tool(
        self,
        user_id: Optional[str],
        team_id: Optional[str],
        agent_id: Optional[str],
    ) -> Callable:
        """Build the add_entity_relationship tool."""

        def add_entity_relationship(
            entity_id: str,
            related_entity_id: str,
            relation: str,
        ) -> str:
            """Add a relationship between two entities.

            Args:
                entity_id: The source entity.
                related_entity_id: The target entity.
                relation: Relationship type (CEO, owns, part_of, etc).

            Returns:
                Confirmation with relationship ID.
            """
            rel_id = self.add_relationship(
                entity_id=entity_id,
                related_entity_id=related_entity_id,
                relation=relation,
                user_id=user_id,
                team_id=team_id,
                agent_id=agent_id,
            )

            return json.dumps({
                "success": rel_id is not None,
                "relationship_id": rel_id,
                "entity_id": entity_id,
                "related_entity_id": related_entity_id,
            })

        return add_entity_relationship

    def _build_update_entity_tool(
        self,
        user_id: Optional[str],
        team_id: Optional[str],
        agent_id: Optional[str],
    ) -> Callable:
        """Build the update_entity tool."""

        def update_entity(
            entity_id: str,
            name: Optional[str] = None,
            description: Optional[str] = None,
            entity_type: Optional[str] = None,
            properties: Optional[Dict[str, str]] = None,
        ) -> str:
            """Update an entity's properties.

            Args:
                entity_id: The entity to update.
                name: New display name (optional).
                description: New description (optional).
                entity_type: New type (optional).
                properties: Key-value properties to set (optional).

            Returns:
                Confirmation message.
            """
            entity = self.get(entity_id, user_id, team_id)

            if not entity:
                return json.dumps({
                    "success": False,
                    "error": f"Entity {entity_id} not found",
                })

            if name is not None:
                entity.name = name
            if description is not None:
                entity.description = description
            if entity_type is not None:
                entity.entity_type = entity_type
            if properties:
                entity.properties.update(properties)

            success = self.save(entity, user_id, team_id, agent_id)

            return json.dumps({
                "success": success,
                "entity_id": entity_id,
            })

        return update_entity

    # =========================================================================
    # Extraction Helpers
    # =========================================================================

    def _format_existing_entities(self, entities: List[EntityMemory]) -> str:
        """Format existing entities for extraction prompt."""
        if not entities:
            return "No existing entities."

        lines = []
        for e in entities:
            lines.append(f"- {e.entity_id} ({e.entity_type}): {e.name or 'unnamed'}")

        return "\n".join(lines)

    def _get_extraction_system_message(self, existing_context: str) -> str:
        """Get system message for extraction LLM."""
        custom = self.config.instructions or ""
        additional = self.config.additional_instructions or ""

        if self.config.system_message:
            return self.config.system_message

        return f"""You are an Entity Memory Manager. Extract facts about third-party entities
mentioned in conversations.

## What to Extract

For each entity mentioned:
1. **Identify**: Name, type (company/project/person/system/product)
2. **Facts**: Concrete information ("Acme uses PostgreSQL")
3. **Events**: Time-bound occurrences ("Acme launched v2 in January")
4. **Relationships**: Connections to other entities ("Bob is CEO of Acme")

## Existing Entities
{existing_context}

## Guidelines

- Use consistent entity_ids (lowercase, underscores: "acme_corp", "john_smith")
- Check existing entities before creating new ones
- Facts should be objective, not opinions
- Only extract entities that are clearly referenced
- Don't extract the user as an entity (they have their own profile)

{custom}
{additional}

Use the provided tools to create entities and add facts/events/relationships.
If no entities are mentioned, do not call any tools.
"""

    def _get_extraction_tools(
        self,
        user_id: Optional[str],
        team_id: Optional[str],
        agent_id: Optional[str],
    ) -> List[Callable]:
        """Get tools for background extraction."""
        tools = []

        if self.config.enable_create_entity:
            tools.append(self._build_create_entity_tool(user_id, team_id, agent_id))

        if self.config.enable_add_fact:
            tools.append(self._build_add_entity_fact_tool(user_id, team_id, agent_id))

        if self.config.enable_add_event:
            tools.append(self._build_add_entity_event_tool(user_id, team_id, agent_id))

        if self.config.enable_add_relationship:
            tools.append(self._build_add_entity_relationship_tool(user_id, team_id, agent_id))

        return tools

    async def _execute_extraction_tool(
        self,
        tool_call: Any,
        user_id: Optional[str],
        team_id: Optional[str],
        agent_id: Optional[str],
    ) -> None:
        """Execute a tool call from extraction."""
        try:
            tool_name = getattr(tool_call, "name", None)
            tool_args = getattr(tool_call, "arguments", {})

            if not tool_name:
                return

            # Map tool names to methods
            tool_map = {
                "create_entity": lambda: self.schema(
                    entity_id=tool_args.get("entity_id"),
                    entity_type=tool_args.get("entity_type", "unknown"),
                    name=tool_args.get("name"),
                    description=tool_args.get("description"),
                ),
                "add_entity_fact": lambda: self.add_fact(
                    entity_id=tool_args.get("entity_id"),
                    fact=tool_args.get("fact"),
                    user_id=user_id,
                    team_id=team_id,
                    agent_id=agent_id,
                ),
                "add_entity_event": lambda: self.add_event(
                    entity_id=tool_args.get("entity_id"),
                    event=tool_args.get("event"),
                    date=tool_args.get("date"),
                    user_id=user_id,
                    team_id=team_id,
                    agent_id=agent_id,
                ),
                "add_entity_relationship": lambda: self.add_relationship(
                    entity_id=tool_args.get("entity_id"),
                    related_entity_id=tool_args.get("related_entity_id"),
                    relation=tool_args.get("relation"),
                    user_id=user_id,
                    team_id=team_id,
                    agent_id=agent_id,
                ),
            }

            if tool_name in tool_map:
                result = tool_map[tool_name]()

                # For create_entity, we need to save
                if tool_name == "create_entity" and result:
                    self.save(result, user_id, team_id, agent_id)

        except Exception as e:
            logger.warning(f"Error executing extraction tool {tool_name}: {e}")
