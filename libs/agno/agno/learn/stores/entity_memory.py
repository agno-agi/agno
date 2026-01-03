"""
Entity Memory Store
===================
Storage backend for Entity Memory learning type.

Stores knowledge about external entities - people, companies, projects, products,
concepts, systems, and any other things the agent interacts with that aren't the
user themselves.

Think of it as:
- UserProfile = what you know about THE USER
- EntityMemory = what you know about EVERYTHING ELSE

Key Features:
- Entity-scoped storage (entity_id + entity_type)
- Three types of memory per entity:
    - Facts (semantic): Timeless truths ("Acme uses PostgreSQL")
    - Events (episodic): Time-bound occurrences ("Acme launched v2 on Jan 15")
    - Relationships (graph): Connections to other entities ("Bob is CEO of Acme")
- Namespace-based sharing control
- Agent tools for CRUD operations
- Background extraction from conversations

Scoping:
- entity_id: Unique identifier (e.g., "acme_corp", "bob_smith")
- entity_type: Category (e.g., "company", "person", "project", "product")
- namespace: Sharing scope:
    - "user": Private to current user
    - "global": Shared with everyone (default)
    - "<custom>": Custom grouping (e.g., "sales_team")

Supported Modes:
- BACKGROUND: Automatic extraction of entity info from conversations
- AGENTIC: Agent calls tools directly to manage entity info
"""

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from os import getenv
from textwrap import dedent
from typing import Any, Callable, Dict, List, Optional, Union

from agno.learn.config import EntityMemoryConfig, LearningMode
from agno.learn.schemas import EntityMemory
from agno.learn.stores.protocol import LearningStore
from agno.utils.log import (
    log_debug,
    log_warning,
    set_log_level_to_debug,
    set_log_level_to_info,
)

try:
    from agno.db.base import AsyncBaseDb, BaseDb
except ImportError:
    pass


@dataclass
class EntityMemoryStore(LearningStore):
    """Storage backend for Entity Memory learning type.

    Stores knowledge about external entities with three types of memory:
    - **Facts**: Semantic memory - timeless truths about the entity
    - **Events**: Episodic memory - time-bound occurrences
    - **Relationships**: Graph edges - connections to other entities

    Each entity is identified by entity_id + entity_type, with namespace for sharing.

    Args:
        config: EntityMemoryConfig with all settings including db and model.
        debug_mode: Enable debug logging.
    """

    config: EntityMemoryConfig = field(default_factory=EntityMemoryConfig)
    debug_mode: bool = False

    # State tracking (internal)
    entity_updated: bool = field(default=False, init=False)
    _schema: Any = field(default=None, init=False)

    def __post_init__(self):
        self._schema = self.config.schema or EntityMemory

        if self.config.mode == LearningMode.PROPOSE:
            log_warning("EntityMemoryStore does not support PROPOSE mode. Falling back to BACKGROUND mode.")
        elif self.config.mode == LearningMode.HITL:
            log_warning("EntityMemoryStore does not support HITL mode. Falling back to BACKGROUND mode.")

    # =========================================================================
    # LearningStore Protocol Implementation
    # =========================================================================

    @property
    def learning_type(self) -> str:
        """Unique identifier for this learning type."""
        return "entity_memory"

    @property
    def schema(self) -> Any:
        """Schema class used for entities."""
        return self._schema

    def recall(
        self,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        user_id: Optional[str] = None,
        namespace: Optional[str] = None,
        **kwargs,
    ) -> Optional[Any]:
        """Retrieve entity memory from storage.

        Args:
            entity_id: The entity to retrieve (required with entity_type).
            entity_type: The type of entity (required with entity_id).
            user_id: User ID for "user" namespace scoping.
            namespace: Filter by namespace.
            **kwargs: Additional context (ignored).

        Returns:
            Entity memory, or None if not found.
        """
        if not entity_id or not entity_type:
            return None

        effective_namespace = namespace or self.config.namespace
        return self.get(
            entity_id=entity_id,
            entity_type=entity_type,
            user_id=user_id,
            namespace=effective_namespace,
        )

    async def arecall(
        self,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        user_id: Optional[str] = None,
        namespace: Optional[str] = None,
        **kwargs,
    ) -> Optional[Any]:
        """Async version of recall."""
        if not entity_id or not entity_type:
            return None

        effective_namespace = namespace or self.config.namespace
        return await self.aget(
            entity_id=entity_id,
            entity_type=entity_type,
            user_id=user_id,
            namespace=effective_namespace,
        )

    def process(
        self,
        messages: List[Any],
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Extract entity information from messages.

        Args:
            messages: Conversation messages to analyze.
            user_id: User context (for "user" namespace scoping).
            agent_id: Agent context (stored for audit).
            team_id: Team context (stored for audit).
            namespace: Namespace to save entities to.
            **kwargs: Additional context (ignored).
        """
        if self.config.mode == LearningMode.AGENTIC:
            return

        if not messages:
            return

        effective_namespace = namespace or self.config.namespace
        self._extract_and_save(
            messages=messages,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            namespace=effective_namespace,
        )

    async def aprocess(
        self,
        messages: List[Any],
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Async version of process."""
        if self.config.mode == LearningMode.AGENTIC:
            return

        if not messages:
            return

        effective_namespace = namespace or self.config.namespace
        await self._aextract_and_save(
            messages=messages,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            namespace=effective_namespace,
        )

    def build_context(self, data: Any) -> str:
        """Build context for the agent.

        Args:
            data: Entity memory data from recall() - single entity or list.

        Returns:
            Context string to inject into the agent's system prompt.
        """
        if not data:
            if self.config.enable_agent_tools:
                return dedent("""\
                    <entity_memory>
                    You have access to entity memory tools to store and retrieve
                    information about people, companies, projects, and other entities.

                    Use `search_entities` to find info, `create_entity` to store new entities.
                    </entity_memory>""")
            return ""

        # Handle single entity or list
        entities = data if isinstance(data, list) else [data]
        if not entities:
            return ""

        # Use schema's get_context_text
        formatted_parts = []
        for entity in entities:
            if hasattr(entity, "get_context_text"):
                formatted_parts.append(entity.get_context_text())
            else:
                formatted_parts.append(self._format_entity_basic(entity=entity))

        formatted = "\n\n---\n\n".join(formatted_parts)

        context = dedent(f"""\
            <entity_memory>
            Known information about relevant entities:

            {formatted}
        """)

        if self.config.enable_agent_tools:
            context += dedent("""
            Use entity memory tools to search, create, or update entities.
            Current conversation takes precedence over stored info.
            </entity_memory>""")
        else:
            context += dedent("""
            Use this for context. Current conversation takes precedence.
            </entity_memory>""")

        return context

    def get_tools(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
        **kwargs,
    ) -> List[Callable]:
        """Get tools to expose to agent.

        Args:
            user_id: User context (for "user" namespace scoping).
            agent_id: Agent context (stored for audit).
            team_id: Team context (stored for audit).
            namespace: Default namespace for operations.
            **kwargs: Additional context (ignored).

        Returns:
            List of callable tools (empty if enable_agent_tools=False).
        """
        if not self.config.enable_agent_tools:
            return []
        return self.get_agent_tools(
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            namespace=namespace,
        )

    async def aget_tools(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
        **kwargs,
    ) -> List[Callable]:
        """Async version of get_tools."""
        if not self.config.enable_agent_tools:
            return []
        return await self.aget_agent_tools(
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            namespace=namespace,
        )

    @property
    def was_updated(self) -> bool:
        """Check if entity was updated in last operation."""
        return self.entity_updated

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def db(self) -> Optional[Union["BaseDb", "AsyncBaseDb"]]:
        """Database backend."""
        return self.config.db

    @property
    def model(self):
        """Model for extraction."""
        return self.config.model

    # =========================================================================
    # Debug/Logging
    # =========================================================================

    def set_log_level(self):
        """Set log level based on debug_mode or environment variable."""
        if self.debug_mode or getenv("AGNO_DEBUG", "false").lower() == "true":
            self.debug_mode = True
            set_log_level_to_debug()
        else:
            set_log_level_to_info()

    # =========================================================================
    # Agent Tools
    # =========================================================================

    def get_agent_tools(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> List[Callable]:
        """Get the tools to expose to the agent.

        Tools are included based on config settings:
        - search_entities (agent_can_search_entities)
        - create_entity (agent_can_create_entity)
        - update_entity (agent_can_update_entity)
        - add_fact, update_fact, delete_fact
        - add_event
        - add_relationship

        Args:
            user_id: User context (for "user" namespace scoping).
            agent_id: Agent context (stored for audit).
            team_id: Team context (stored for audit).
            namespace: Default namespace for operations.

        Returns:
            List of callable tools.
        """
        tools = []
        effective_namespace = namespace or self.config.namespace

        if self.config.agent_can_search_entities:
            tools.append(
                self._create_search_entities_tool(
                    user_id=user_id,
                    namespace=effective_namespace,
                )
            )

        if self.config.agent_can_create_entity:
            tools.append(
                self._create_create_entity_tool(
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    namespace=effective_namespace,
                )
            )

        if self.config.agent_can_update_entity:
            tools.append(
                self._create_update_entity_tool(
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    namespace=effective_namespace,
                )
            )

        if self.config.enable_add_fact:
            tools.append(
                self._create_add_fact_tool(
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    namespace=effective_namespace,
                )
            )

        if self.config.enable_update_fact:
            tools.append(
                self._create_update_fact_tool(
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    namespace=effective_namespace,
                )
            )

        if self.config.enable_delete_fact:
            tools.append(
                self._create_delete_fact_tool(
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    namespace=effective_namespace,
                )
            )

        if self.config.enable_add_event:
            tools.append(
                self._create_add_event_tool(
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    namespace=effective_namespace,
                )
            )

        if self.config.enable_add_relationship:
            tools.append(
                self._create_add_relationship_tool(
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    namespace=effective_namespace,
                )
            )

        return tools

    async def aget_agent_tools(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> List[Callable]:
        """Async version of get_agent_tools."""
        tools = []
        effective_namespace = namespace or self.config.namespace

        if self.config.agent_can_search_entities:
            tools.append(
                self._create_async_search_entities_tool(
                    user_id=user_id,
                    namespace=effective_namespace,
                )
            )

        if self.config.agent_can_create_entity:
            tools.append(
                self._create_async_create_entity_tool(
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    namespace=effective_namespace,
                )
            )

        if self.config.agent_can_update_entity:
            tools.append(
                self._create_async_update_entity_tool(
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    namespace=effective_namespace,
                )
            )

        if self.config.enable_add_fact:
            tools.append(
                self._create_async_add_fact_tool(
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    namespace=effective_namespace,
                )
            )

        if self.config.enable_update_fact:
            tools.append(
                self._create_async_update_fact_tool(
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    namespace=effective_namespace,
                )
            )

        if self.config.enable_delete_fact:
            tools.append(
                self._create_async_delete_fact_tool(
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    namespace=effective_namespace,
                )
            )

        if self.config.enable_add_event:
            tools.append(
                self._create_async_add_event_tool(
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    namespace=effective_namespace,
                )
            )

        if self.config.enable_add_relationship:
            tools.append(
                self._create_async_add_relationship_tool(
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    namespace=effective_namespace,
                )
            )

        return tools

    # =========================================================================
    # Tool: search_entities
    # =========================================================================

    def _create_search_entities_tool(
        self,
        user_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> Callable:
        """Create the search_entities tool."""

        def search_entities(
            query: str,
            entity_type: Optional[str] = None,
            limit: int = 5,
        ) -> str:
            """Search for entities in memory.

            Use this to find information about people, companies, projects,
            or other entities that have been stored.

            Args:
                query: What to search for (e.g., "Acme", "PostgreSQL", "CEO")
                entity_type: Filter by type (e.g., "person", "company", "project")
                limit: Maximum results to return (default: 5)

            Returns:
                Formatted list of matching entities with their facts.
            """
            results = self.search(
                query=query,
                entity_type=entity_type,
                user_id=user_id,
                namespace=namespace,
                limit=limit,
            )

            if not results:
                return "No matching entities found."

            formatted = self._format_entities_list(entities=results)
            return f"Found {len(results)} entity/entities:\n\n{formatted}"

        return search_entities

    def _create_async_search_entities_tool(
        self,
        user_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> Callable:
        """Create the async search_entities tool."""

        async def search_entities(
            query: str,
            entity_type: Optional[str] = None,
            limit: int = 5,
        ) -> str:
            """Search for entities in memory.

            Use this to find information about people, companies, projects,
            or other entities that have been stored.

            Args:
                query: What to search for (e.g., "Acme", "PostgreSQL", "CEO")
                entity_type: Filter by type (e.g., "person", "company", "project")
                limit: Maximum results to return (default: 5)

            Returns:
                Formatted list of matching entities with their facts.
            """
            results = await self.asearch(
                query=query,
                entity_type=entity_type,
                user_id=user_id,
                namespace=namespace,
                limit=limit,
            )

            if not results:
                return "No matching entities found."

            formatted = self._format_entities_list(entities=results)
            return f"Found {len(results)} entity/entities:\n\n{formatted}"

        return search_entities

    # =========================================================================
    # Tool: create_entity
    # =========================================================================

    def _create_create_entity_tool(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> Callable:
        """Create the create_entity tool."""

        def create_entity(
            entity_id: str,
            entity_type: str,
            name: str,
            description: Optional[str] = None,
            properties: Optional[Dict[str, str]] = None,
        ) -> str:
            """Create a new entity in memory.

            Use this to store information about a person, company, project,
            or other entity mentioned in the conversation.

            Args:
                entity_id: Unique identifier (lowercase, underscores: "acme_corp")
                entity_type: Type ("person", "company", "project", "product", etc.)
                name: Display name for the entity
                description: Brief description of what this entity is
                properties: Key-value properties (e.g., {"industry": "fintech"})

            Returns:
                Confirmation message.
            """
            success = self.create_entity(
                entity_id=entity_id,
                entity_type=entity_type,
                name=name,
                description=description,
                properties=properties,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=namespace,
            )

            if success:
                self.entity_updated = True
                return f"Entity created: {entity_type}/{entity_id} ({name})"
            return f"Failed to create entity (may already exist)"

        return create_entity

    def _create_async_create_entity_tool(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> Callable:
        """Create the async create_entity tool."""

        async def create_entity(
            entity_id: str,
            entity_type: str,
            name: str,
            description: Optional[str] = None,
            properties: Optional[Dict[str, str]] = None,
        ) -> str:
            """Create a new entity in memory.

            Use this to store information about a person, company, project,
            or other entity mentioned in the conversation.

            Args:
                entity_id: Unique identifier (lowercase, underscores: "acme_corp")
                entity_type: Type ("person", "company", "project", "product", etc.)
                name: Display name for the entity
                description: Brief description of what this entity is
                properties: Key-value properties (e.g., {"industry": "fintech"})

            Returns:
                Confirmation message.
            """
            success = await self.acreate_entity(
                entity_id=entity_id,
                entity_type=entity_type,
                name=name,
                description=description,
                properties=properties,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=namespace,
            )

            if success:
                self.entity_updated = True
                return f"Entity created: {entity_type}/{entity_id} ({name})"
            return f"Failed to create entity (may already exist)"

        return create_entity

    # =========================================================================
    # Tool: update_entity
    # =========================================================================

    def _create_update_entity_tool(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> Callable:
        """Create the update_entity tool."""

        def update_entity(
            entity_id: str,
            entity_type: str,
            name: Optional[str] = None,
            description: Optional[str] = None,
            properties: Optional[Dict[str, str]] = None,
        ) -> str:
            """Update an existing entity's core properties.

            Use this to modify an entity's name, description, or properties.
            Only provided fields will be updated.

            Args:
                entity_id: The entity's identifier
                entity_type: Type of entity
                name: New display name (optional)
                description: New description (optional)
                properties: Properties to add/update (optional, merged with existing)

            Returns:
                Confirmation message.
            """
            success = self.update_entity(
                entity_id=entity_id,
                entity_type=entity_type,
                name=name,
                description=description,
                properties=properties,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=namespace,
            )

            if success:
                self.entity_updated = True
                return f"Entity updated: {entity_type}/{entity_id}"
            return f"Entity not found: {entity_type}/{entity_id}"

        return update_entity

    def _create_async_update_entity_tool(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> Callable:
        """Create the async update_entity tool."""

        async def update_entity(
            entity_id: str,
            entity_type: str,
            name: Optional[str] = None,
            description: Optional[str] = None,
            properties: Optional[Dict[str, str]] = None,
        ) -> str:
            """Update an existing entity's core properties.

            Use this to modify an entity's name, description, or properties.
            Only provided fields will be updated.

            Args:
                entity_id: The entity's identifier
                entity_type: Type of entity
                name: New display name (optional)
                description: New description (optional)
                properties: Properties to add/update (optional, merged with existing)

            Returns:
                Confirmation message.
            """
            success = await self.aupdate_entity(
                entity_id=entity_id,
                entity_type=entity_type,
                name=name,
                description=description,
                properties=properties,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=namespace,
            )

            if success:
                self.entity_updated = True
                return f"Entity updated: {entity_type}/{entity_id}"
            return f"Entity not found: {entity_type}/{entity_id}"

        return update_entity

    # =========================================================================
    # Tool: add_fact
    # =========================================================================

    def _create_add_fact_tool(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> Callable:
        """Create the add_fact tool."""

        def add_fact(
            entity_id: str,
            entity_type: str,
            fact: str,
        ) -> str:
            """Add a fact to an entity.

            Facts are timeless truths about the entity (semantic memory).
            Examples: "Uses PostgreSQL", "Based in San Francisco", "Founded in 2020"

            Args:
                entity_id: The entity's identifier
                entity_type: Type of entity
                fact: The fact to add

            Returns:
                Confirmation message with fact ID.
            """
            fact_id = self.add_fact(
                entity_id=entity_id,
                entity_type=entity_type,
                fact=fact,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=namespace,
            )

            if fact_id:
                self.entity_updated = True
                return f"Fact added to {entity_type}/{entity_id} (id: {fact_id})"
            return f"Failed to add fact (entity may not exist)"

        return add_fact

    def _create_async_add_fact_tool(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> Callable:
        """Create the async add_fact tool."""

        async def add_fact(
            entity_id: str,
            entity_type: str,
            fact: str,
        ) -> str:
            """Add a fact to an entity.

            Facts are timeless truths about the entity (semantic memory).
            Examples: "Uses PostgreSQL", "Based in San Francisco", "Founded in 2020"

            Args:
                entity_id: The entity's identifier
                entity_type: Type of entity
                fact: The fact to add

            Returns:
                Confirmation message with fact ID.
            """
            fact_id = await self.aadd_fact(
                entity_id=entity_id,
                entity_type=entity_type,
                fact=fact,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=namespace,
            )

            if fact_id:
                self.entity_updated = True
                return f"Fact added to {entity_type}/{entity_id} (id: {fact_id})"
            return f"Failed to add fact (entity may not exist)"

        return add_fact

    # =========================================================================
    # Tool: update_fact
    # =========================================================================

    def _create_update_fact_tool(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> Callable:
        """Create the update_fact tool."""

        def update_fact(
            entity_id: str,
            entity_type: str,
            fact_id: str,
            fact: str,
        ) -> str:
            """Update an existing fact on an entity.

            Args:
                entity_id: The entity's identifier
                entity_type: Type of entity
                fact_id: ID of the fact to update
                fact: New fact content

            Returns:
                Confirmation message.
            """
            success = self.update_fact(
                entity_id=entity_id,
                entity_type=entity_type,
                fact_id=fact_id,
                fact=fact,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=namespace,
            )

            if success:
                self.entity_updated = True
                return f"Fact updated on {entity_type}/{entity_id}"
            return f"Fact not found: {fact_id}"

        return update_fact

    def _create_async_update_fact_tool(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> Callable:
        """Create the async update_fact tool."""

        async def update_fact(
            entity_id: str,
            entity_type: str,
            fact_id: str,
            fact: str,
        ) -> str:
            """Update an existing fact on an entity.

            Args:
                entity_id: The entity's identifier
                entity_type: Type of entity
                fact_id: ID of the fact to update
                fact: New fact content

            Returns:
                Confirmation message.
            """
            success = await self.aupdate_fact(
                entity_id=entity_id,
                entity_type=entity_type,
                fact_id=fact_id,
                fact=fact,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=namespace,
            )

            if success:
                self.entity_updated = True
                return f"Fact updated on {entity_type}/{entity_id}"
            return f"Fact not found: {fact_id}"

        return update_fact

    # =========================================================================
    # Tool: delete_fact
    # =========================================================================

    def _create_delete_fact_tool(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> Callable:
        """Create the delete_fact tool."""

        def delete_fact(
            entity_id: str,
            entity_type: str,
            fact_id: str,
        ) -> str:
            """Delete a fact from an entity.

            Args:
                entity_id: The entity's identifier
                entity_type: Type of entity
                fact_id: ID of the fact to delete

            Returns:
                Confirmation message.
            """
            success = self.delete_fact(
                entity_id=entity_id,
                entity_type=entity_type,
                fact_id=fact_id,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=namespace,
            )

            if success:
                self.entity_updated = True
                return f"Fact deleted from {entity_type}/{entity_id}"
            return f"Fact not found: {fact_id}"

        return delete_fact

    def _create_async_delete_fact_tool(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> Callable:
        """Create the async delete_fact tool."""

        async def delete_fact(
            entity_id: str,
            entity_type: str,
            fact_id: str,
        ) -> str:
            """Delete a fact from an entity.

            Args:
                entity_id: The entity's identifier
                entity_type: Type of entity
                fact_id: ID of the fact to delete

            Returns:
                Confirmation message.
            """
            success = await self.adelete_fact(
                entity_id=entity_id,
                entity_type=entity_type,
                fact_id=fact_id,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=namespace,
            )

            if success:
                self.entity_updated = True
                return f"Fact deleted from {entity_type}/{entity_id}"
            return f"Fact not found: {fact_id}"

        return delete_fact

    # =========================================================================
    # Tool: add_event
    # =========================================================================

    def _create_add_event_tool(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> Callable:
        """Create the add_event tool."""

        def add_event(
            entity_id: str,
            entity_type: str,
            event: str,
            date: Optional[str] = None,
        ) -> str:
            """Add an event to an entity.

            Events are time-bound occurrences (episodic memory).
            Examples: "Launched v2.0", "Acquired by BigCorp", "Had outage"

            Args:
                entity_id: The entity's identifier
                entity_type: Type of entity
                event: Description of what happened
                date: When it happened (ISO format or natural language)

            Returns:
                Confirmation message with event ID.
            """
            event_id = self.add_event(
                entity_id=entity_id,
                entity_type=entity_type,
                event=event,
                date=date,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=namespace,
            )

            if event_id:
                self.entity_updated = True
                return f"Event added to {entity_type}/{entity_id} (id: {event_id})"
            return f"Failed to add event (entity may not exist)"

        return add_event

    def _create_async_add_event_tool(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> Callable:
        """Create the async add_event tool."""

        async def add_event(
            entity_id: str,
            entity_type: str,
            event: str,
            date: Optional[str] = None,
        ) -> str:
            """Add an event to an entity.

            Events are time-bound occurrences (episodic memory).
            Examples: "Launched v2.0", "Acquired by BigCorp", "Had outage"

            Args:
                entity_id: The entity's identifier
                entity_type: Type of entity
                event: Description of what happened
                date: When it happened (ISO format or natural language)

            Returns:
                Confirmation message with event ID.
            """
            event_id = await self.aadd_event(
                entity_id=entity_id,
                entity_type=entity_type,
                event=event,
                date=date,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=namespace,
            )

            if event_id:
                self.entity_updated = True
                return f"Event added to {entity_type}/{entity_id} (id: {event_id})"
            return f"Failed to add event (entity may not exist)"

        return add_event

    # =========================================================================
    # Tool: add_relationship
    # =========================================================================

    def _create_add_relationship_tool(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> Callable:
        """Create the add_relationship tool."""

        def add_relationship(
            entity_id: str,
            entity_type: str,
            related_entity_id: str,
            relation: str,
            direction: str = "outgoing",
        ) -> str:
            """Add a relationship between entities.

            Relationships are graph edges connecting entities.
            Examples: "CEO of", "owns", "part_of", "competitor_of"

            Args:
                entity_id: The source entity's identifier
                entity_type: Type of source entity
                related_entity_id: The target entity's identifier
                relation: Type of relationship ("CEO", "owns", "part_of", etc.)
                direction: "outgoing" (this → other) or "incoming" (other → this)

            Returns:
                Confirmation message with relationship ID.
            """
            rel_id = self.add_relationship(
                entity_id=entity_id,
                entity_type=entity_type,
                related_entity_id=related_entity_id,
                relation=relation,
                direction=direction,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=namespace,
            )

            if rel_id:
                self.entity_updated = True
                return f"Relationship added: {entity_id} --[{relation}]--> {related_entity_id} (id: {rel_id})"
            return f"Failed to add relationship (entity may not exist)"

        return add_relationship

    def _create_async_add_relationship_tool(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> Callable:
        """Create the async add_relationship tool."""

        async def add_relationship(
            entity_id: str,
            entity_type: str,
            related_entity_id: str,
            relation: str,
            direction: str = "outgoing",
        ) -> str:
            """Add a relationship between entities.

            Relationships are graph edges connecting entities.
            Examples: "CEO of", "owns", "part_of", "competitor_of"

            Args:
                entity_id: The source entity's identifier
                entity_type: Type of source entity
                related_entity_id: The target entity's identifier
                relation: Type of relationship ("CEO", "owns", "part_of", etc.)
                direction: "outgoing" (this → other) or "incoming" (other → this)

            Returns:
                Confirmation message with relationship ID.
            """
            rel_id = await self.aadd_relationship(
                entity_id=entity_id,
                entity_type=entity_type,
                related_entity_id=related_entity_id,
                relation=relation,
                direction=direction,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=namespace,
            )

            if rel_id:
                self.entity_updated = True
                return f"Relationship added: {entity_id} --[{relation}]--> {related_entity_id} (id: {rel_id})"
            return f"Failed to add relationship (entity may not exist)"

        return add_relationship

    # =========================================================================
    # Read Operations
    # =========================================================================

    def get(
        self,
        entity_id: str,
        entity_type: str,
        user_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> Optional[EntityMemory]:
        """Retrieve entity by entity_id and entity_type.

        Args:
            entity_id: The unique entity identifier.
            entity_type: The type of entity.
            user_id: User ID for "user" namespace scoping.
            namespace: Namespace to search in.

        Returns:
            EntityMemory instance, or None if not found.
        """
        if not self.db:
            return None

        effective_namespace = namespace or self.config.namespace

        try:
            result = self.db.get_learning(
                learning_type=self.learning_type,
                entity_id=entity_id,
                entity_type=entity_type,
                namespace=effective_namespace,
                user_id=user_id if effective_namespace == "user" else None,
            )

            if result and result.get("content"):
                return self.schema.from_dict(result["content"])

            return None

        except Exception as e:
            log_debug(f"EntityMemoryStore.get failed for {entity_type}/{entity_id}: {e}")
            return None

    async def aget(
        self,
        entity_id: str,
        entity_type: str,
        user_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> Optional[EntityMemory]:
        """Async version of get."""
        if not self.db:
            return None

        effective_namespace = namespace or self.config.namespace

        try:
            if isinstance(self.db, AsyncBaseDb):
                result = await self.db.get_learning(
                    learning_type=self.learning_type,
                    entity_id=entity_id,
                    entity_type=entity_type,
                    namespace=effective_namespace,
                    user_id=user_id if effective_namespace == "user" else None,
                )
            else:
                result = self.db.get_learning(
                    learning_type=self.learning_type,
                    entity_id=entity_id,
                    entity_type=entity_type,
                    namespace=effective_namespace,
                    user_id=user_id if effective_namespace == "user" else None,
                )

            if result and result.get("content"):
                return self.schema.from_dict(result["content"])

            return None

        except Exception as e:
            log_debug(f"EntityMemoryStore.aget failed for {entity_type}/{entity_id}: {e}")
            return None

    # =========================================================================
    # Search Operations
    # =========================================================================

    def search(
        self,
        query: str,
        entity_type: Optional[str] = None,
        user_id: Optional[str] = None,
        namespace: Optional[str] = None,
        limit: int = 10,
    ) -> List[EntityMemory]:
        """Search for entities matching query.

        Args:
            query: Search query (matched against name, facts, events, etc.).
            entity_type: Filter by entity type.
            user_id: User ID for "user" namespace scoping.
            namespace: Filter by namespace.
            limit: Maximum results to return.

        Returns:
            List of matching EntityMemory objects.
        """
        if not self.db:
            return []

        effective_namespace = namespace or self.config.namespace

        try:
            results = self.db.get_learnings(
                learning_type=self.learning_type,
                entity_type=entity_type,
                namespace=effective_namespace,
                user_id=user_id if effective_namespace == "user" else None,
                limit=limit * 3,  # Over-fetch for filtering
            )

            entities = []
            query_lower = query.lower()

            for result in results or []:
                content = result.get("content", {})
                if self._matches_query(content=content, query=query_lower):
                    entity = self.schema.from_dict(content)
                    if entity:
                        entities.append(entity)

                if len(entities) >= limit:
                    break

            log_debug(f"EntityMemoryStore.search: found {len(entities)} entities for query: {query[:50]}...")
            return entities

        except Exception as e:
            log_debug(f"EntityMemoryStore.search failed: {e}")
            return []

    async def asearch(
        self,
        query: str,
        entity_type: Optional[str] = None,
        user_id: Optional[str] = None,
        namespace: Optional[str] = None,
        limit: int = 10,
    ) -> List[EntityMemory]:
        """Async version of search."""
        if not self.db:
            return []

        effective_namespace = namespace or self.config.namespace

        try:
            if isinstance(self.db, AsyncBaseDb):
                results = await self.db.get_learnings(
                    learning_type=self.learning_type,
                    entity_type=entity_type,
                    namespace=effective_namespace,
                    user_id=user_id if effective_namespace == "user" else None,
                    limit=limit * 3,
                )
            else:
                results = self.db.get_learnings(
                    learning_type=self.learning_type,
                    entity_type=entity_type,
                    namespace=effective_namespace,
                    user_id=user_id if effective_namespace == "user" else None,
                    limit=limit * 3,
                )

            entities = []
            query_lower = query.lower()

            for result in results or []:
                content = result.get("content", {})
                if self._matches_query(content=content, query=query_lower):
                    entity = self.schema.from_dict(content)
                    if entity:
                        entities.append(entity)

                if len(entities) >= limit:
                    break

            log_debug(f"EntityMemoryStore.asearch: found {len(entities)} entities for query: {query[:50]}...")
            return entities

        except Exception as e:
            log_debug(f"EntityMemoryStore.asearch failed: {e}")
            return []

    def _matches_query(self, content: Dict[str, Any], query: str) -> bool:
        """Check if entity content matches search query."""
        # Check name
        name = content.get("name", "")
        if name and query in name.lower():
            return True

        # Check entity_id
        entity_id = content.get("entity_id", "")
        if entity_id and query in entity_id.lower():
            return True

        # Check description
        description = content.get("description", "")
        if description and query in description.lower():
            return True

        # Check properties
        properties = content.get("properties", {})
        for value in properties.values():
            if query in str(value).lower():
                return True

        # Check facts
        facts = content.get("facts", [])
        for fact in facts:
            fact_content = fact.get("content", "") if isinstance(fact, dict) else str(fact)
            if query in fact_content.lower():
                return True

        # Check events
        events = content.get("events", [])
        for event in events:
            event_content = event.get("content", "") if isinstance(event, dict) else str(event)
            if query in event_content.lower():
                return True

        # Check relationships
        relationships = content.get("relationships", [])
        for rel in relationships:
            if isinstance(rel, dict):
                if query in rel.get("entity_id", "").lower():
                    return True
                if query in rel.get("relation", "").lower():
                    return True

        return False

    # =========================================================================
    # Create Operations
    # =========================================================================

    def create_entity(
        self,
        entity_id: str,
        entity_type: str,
        name: str,
        description: Optional[str] = None,
        properties: Optional[Dict[str, str]] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> bool:
        """Create a new entity.

        Args:
            entity_id: Unique identifier for the entity.
            entity_type: Type of entity.
            name: Display name.
            description: Brief description.
            properties: Key-value properties.
            user_id: User ID (required for "user" namespace).
            agent_id: Agent context (stored for audit).
            team_id: Team context (stored for audit).
            namespace: Namespace for scoping.

        Returns:
            True if created, False if already exists or error.
        """
        if not self.db:
            return False

        effective_namespace = namespace or self.config.namespace

        # Validate "user" namespace has user_id
        if effective_namespace == "user" and not user_id:
            log_warning("EntityMemoryStore.create_entity: 'user' namespace requires user_id")
            return False

        # Check if already exists
        existing = self.get(
            entity_id=entity_id,
            entity_type=entity_type,
            user_id=user_id,
            namespace=effective_namespace,
        )
        if existing:
            log_debug(f"EntityMemoryStore.create_entity: entity already exists {entity_type}/{entity_id}")
            return False

        try:
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

            entity = self.schema(
                entity_id=entity_id,
                entity_type=entity_type,
                name=name,
                description=description,
                properties=properties or {},
                facts=[],
                events=[],
                relationships=[],
                namespace=effective_namespace,
                user_id=user_id if effective_namespace == "user" else None,
                agent_id=agent_id,
                team_id=team_id,
                created_at=now,
                updated_at=now,
            )

            self.db.upsert_learning(
                id=self._build_entity_db_id(entity_id, entity_type, effective_namespace),
                learning_type=self.learning_type,
                entity_id=entity_id,
                entity_type=entity_type,
                namespace=effective_namespace,
                user_id=user_id if effective_namespace == "user" else None,
                agent_id=agent_id,
                team_id=team_id,
                content=entity.to_dict(),
            )

            log_debug(f"EntityMemoryStore.create_entity: created {entity_type}/{entity_id}")
            return True

        except Exception as e:
            log_debug(f"EntityMemoryStore.create_entity failed: {e}")
            return False

    async def acreate_entity(
        self,
        entity_id: str,
        entity_type: str,
        name: str,
        description: Optional[str] = None,
        properties: Optional[Dict[str, str]] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> bool:
        """Async version of create_entity."""
        if not self.db:
            return False

        effective_namespace = namespace or self.config.namespace

        if effective_namespace == "user" and not user_id:
            log_warning("EntityMemoryStore.acreate_entity: 'user' namespace requires user_id")
            return False

        existing = await self.aget(
            entity_id=entity_id,
            entity_type=entity_type,
            user_id=user_id,
            namespace=effective_namespace,
        )
        if existing:
            log_debug(f"EntityMemoryStore.acreate_entity: entity already exists {entity_type}/{entity_id}")
            return False

        try:
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

            entity = self.schema(
                entity_id=entity_id,
                entity_type=entity_type,
                name=name,
                description=description,
                properties=properties or {},
                facts=[],
                events=[],
                relationships=[],
                namespace=effective_namespace,
                user_id=user_id if effective_namespace == "user" else None,
                agent_id=agent_id,
                team_id=team_id,
                created_at=now,
                updated_at=now,
            )

            if isinstance(self.db, AsyncBaseDb):
                await self.db.upsert_learning(
                    id=self._build_entity_db_id(entity_id, entity_type, effective_namespace),
                    learning_type=self.learning_type,
                    entity_id=entity_id,
                    entity_type=entity_type,
                    namespace=effective_namespace,
                    user_id=user_id if effective_namespace == "user" else None,
                    agent_id=agent_id,
                    team_id=team_id,
                    content=entity.to_dict(),
                )
            else:
                self.db.upsert_learning(
                    id=self._build_entity_db_id(entity_id, entity_type, effective_namespace),
                    learning_type=self.learning_type,
                    entity_id=entity_id,
                    entity_type=entity_type,
                    namespace=effective_namespace,
                    user_id=user_id if effective_namespace == "user" else None,
                    agent_id=agent_id,
                    team_id=team_id,
                    content=entity.to_dict(),
                )

            log_debug(f"EntityMemoryStore.acreate_entity: created {entity_type}/{entity_id}")
            return True

        except Exception as e:
            log_debug(f"EntityMemoryStore.acreate_entity failed: {e}")
            return False

    # =========================================================================
    # Update Operations
    # =========================================================================

    def update_entity(
        self,
        entity_id: str,
        entity_type: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        properties: Optional[Dict[str, str]] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> bool:
        """Update an existing entity's core properties.

        Args:
            entity_id: The entity's identifier.
            entity_type: Type of entity.
            name: New display name (optional).
            description: New description (optional).
            properties: Properties to merge (optional).
            user_id: User ID for namespace scoping.
            agent_id: Agent context.
            team_id: Team context.
            namespace: Namespace to search in.

        Returns:
            True if updated, False if not found.
        """
        effective_namespace = namespace or self.config.namespace

        entity = self.get(
            entity_id=entity_id,
            entity_type=entity_type,
            user_id=user_id,
            namespace=effective_namespace,
        )

        if not entity:
            return False

        # Update fields
        if name is not None:
            entity.name = name
        if description is not None:
            entity.description = description
        if properties is not None:
            entity.properties = {**(entity.properties or {}), **properties}

        entity.updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        return self._save_entity(
            entity=entity,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            namespace=effective_namespace,
        )

    async def aupdate_entity(
        self,
        entity_id: str,
        entity_type: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        properties: Optional[Dict[str, str]] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> bool:
        """Async version of update_entity."""
        effective_namespace = namespace or self.config.namespace

        entity = await self.aget(
            entity_id=entity_id,
            entity_type=entity_type,
            user_id=user_id,
            namespace=effective_namespace,
        )

        if not entity:
            return False

        if name is not None:
            entity.name = name
        if description is not None:
            entity.description = description
        if properties is not None:
            entity.properties = {**(entity.properties or {}), **properties}

        entity.updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        return await self._asave_entity(
            entity=entity,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            namespace=effective_namespace,
        )

    # =========================================================================
    # Fact Operations
    # =========================================================================

    def add_fact(
        self,
        entity_id: str,
        entity_type: str,
        fact: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> Optional[str]:
        """Add a fact to an entity.

        Returns:
            Fact ID if added, None if entity not found.
        """
        effective_namespace = namespace or self.config.namespace

        entity = self.get(
            entity_id=entity_id,
            entity_type=entity_type,
            user_id=user_id,
            namespace=effective_namespace,
        )

        if not entity:
            return None

        fact_id = entity.add_fact(fact)
        entity.updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        success = self._save_entity(
            entity=entity,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            namespace=effective_namespace,
        )

        return fact_id if success else None

    async def aadd_fact(
        self,
        entity_id: str,
        entity_type: str,
        fact: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> Optional[str]:
        """Async version of add_fact."""
        effective_namespace = namespace or self.config.namespace

        entity = await self.aget(
            entity_id=entity_id,
            entity_type=entity_type,
            user_id=user_id,
            namespace=effective_namespace,
        )

        if not entity:
            return None

        fact_id = entity.add_fact(fact)
        entity.updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        success = await self._asave_entity(
            entity=entity,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            namespace=effective_namespace,
        )

        return fact_id if success else None

    def update_fact(
        self,
        entity_id: str,
        entity_type: str,
        fact_id: str,
        fact: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> bool:
        """Update an existing fact."""
        effective_namespace = namespace or self.config.namespace

        entity = self.get(
            entity_id=entity_id,
            entity_type=entity_type,
            user_id=user_id,
            namespace=effective_namespace,
        )

        if not entity:
            return False

        if not entity.update_fact(fact_id, fact):
            return False

        entity.updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        return self._save_entity(
            entity=entity,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            namespace=effective_namespace,
        )

    async def aupdate_fact(
        self,
        entity_id: str,
        entity_type: str,
        fact_id: str,
        fact: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> bool:
        """Async version of update_fact."""
        effective_namespace = namespace or self.config.namespace

        entity = await self.aget(
            entity_id=entity_id,
            entity_type=entity_type,
            user_id=user_id,
            namespace=effective_namespace,
        )

        if not entity:
            return False

        if not entity.update_fact(fact_id, fact):
            return False

        entity.updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        return await self._asave_entity(
            entity=entity,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            namespace=effective_namespace,
        )

    def delete_fact(
        self,
        entity_id: str,
        entity_type: str,
        fact_id: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> bool:
        """Delete a fact from an entity."""
        effective_namespace = namespace or self.config.namespace

        entity = self.get(
            entity_id=entity_id,
            entity_type=entity_type,
            user_id=user_id,
            namespace=effective_namespace,
        )

        if not entity:
            return False

        if not entity.delete_fact(fact_id):
            return False

        entity.updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        return self._save_entity(
            entity=entity,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            namespace=effective_namespace,
        )

    async def adelete_fact(
        self,
        entity_id: str,
        entity_type: str,
        fact_id: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> bool:
        """Async version of delete_fact."""
        effective_namespace = namespace or self.config.namespace

        entity = await self.aget(
            entity_id=entity_id,
            entity_type=entity_type,
            user_id=user_id,
            namespace=effective_namespace,
        )

        if not entity:
            return False

        if not entity.delete_fact(fact_id):
            return False

        entity.updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        return await self._asave_entity(
            entity=entity,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            namespace=effective_namespace,
        )

    # =========================================================================
    # Event Operations
    # =========================================================================

    def add_event(
        self,
        entity_id: str,
        entity_type: str,
        event: str,
        date: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> Optional[str]:
        """Add an event to an entity.

        Returns:
            Event ID if added, None if entity not found.
        """
        effective_namespace = namespace or self.config.namespace

        entity = self.get(
            entity_id=entity_id,
            entity_type=entity_type,
            user_id=user_id,
            namespace=effective_namespace,
        )

        if not entity:
            return None

        event_id = entity.add_event(event, date=date)
        entity.updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        success = self._save_entity(
            entity=entity,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            namespace=effective_namespace,
        )

        return event_id if success else None

    async def aadd_event(
        self,
        entity_id: str,
        entity_type: str,
        event: str,
        date: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> Optional[str]:
        """Async version of add_event."""
        effective_namespace = namespace or self.config.namespace

        entity = await self.aget(
            entity_id=entity_id,
            entity_type=entity_type,
            user_id=user_id,
            namespace=effective_namespace,
        )

        if not entity:
            return None

        event_id = entity.add_event(event, date=date)
        entity.updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        success = await self._asave_entity(
            entity=entity,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            namespace=effective_namespace,
        )

        return event_id if success else None

    # =========================================================================
    # Relationship Operations
    # =========================================================================

    def add_relationship(
        self,
        entity_id: str,
        entity_type: str,
        related_entity_id: str,
        relation: str,
        direction: str = "outgoing",
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> Optional[str]:
        """Add a relationship to an entity.

        Returns:
            Relationship ID if added, None if entity not found.
        """
        effective_namespace = namespace or self.config.namespace

        entity = self.get(
            entity_id=entity_id,
            entity_type=entity_type,
            user_id=user_id,
            namespace=effective_namespace,
        )

        if not entity:
            return None

        rel_id = entity.add_relationship(related_entity_id, relation, direction=direction)
        entity.updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        success = self._save_entity(
            entity=entity,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            namespace=effective_namespace,
        )

        return rel_id if success else None

    async def aadd_relationship(
        self,
        entity_id: str,
        entity_type: str,
        related_entity_id: str,
        relation: str,
        direction: str = "outgoing",
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> Optional[str]:
        """Async version of add_relationship."""
        effective_namespace = namespace or self.config.namespace

        entity = await self.aget(
            entity_id=entity_id,
            entity_type=entity_type,
            user_id=user_id,
            namespace=effective_namespace,
        )

        if not entity:
            return None

        rel_id = entity.add_relationship(related_entity_id, relation, direction=direction)
        entity.updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        success = await self._asave_entity(
            entity=entity,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            namespace=effective_namespace,
        )

        return rel_id if success else None

    # =========================================================================
    # Internal Save Helpers
    # =========================================================================

    def _save_entity(
        self,
        entity: EntityMemory,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> bool:
        """Save entity to database."""
        if not self.db:
            return False

        effective_namespace = namespace or self.config.namespace

        try:
            content = entity.to_dict()
            if not content:
                return False

            self.db.upsert_learning(
                id=self._build_entity_db_id(entity.entity_id, entity.entity_type, effective_namespace),
                learning_type=self.learning_type,
                entity_id=entity.entity_id,
                entity_type=entity.entity_type,
                namespace=effective_namespace,
                user_id=user_id if effective_namespace == "user" else None,
                agent_id=agent_id,
                team_id=team_id,
                content=content,
            )

            return True

        except Exception as e:
            log_debug(f"EntityMemoryStore._save_entity failed: {e}")
            return False

    async def _asave_entity(
        self,
        entity: EntityMemory,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> bool:
        """Async version of _save_entity."""
        if not self.db:
            return False

        effective_namespace = namespace or self.config.namespace

        try:
            content = entity.to_dict()
            if not content:
                return False

            if isinstance(self.db, AsyncBaseDb):
                await self.db.upsert_learning(
                    id=self._build_entity_db_id(entity.entity_id, entity.entity_type, effective_namespace),
                    learning_type=self.learning_type,
                    entity_id=entity.entity_id,
                    entity_type=entity.entity_type,
                    namespace=effective_namespace,
                    user_id=user_id if effective_namespace == "user" else None,
                    agent_id=agent_id,
                    team_id=team_id,
                    content=content,
                )
            else:
                self.db.upsert_learning(
                    id=self._build_entity_db_id(entity.entity_id, entity.entity_type, effective_namespace),
                    learning_type=self.learning_type,
                    entity_id=entity.entity_id,
                    entity_type=entity.entity_type,
                    namespace=effective_namespace,
                    user_id=user_id if effective_namespace == "user" else None,
                    agent_id=agent_id,
                    team_id=team_id,
                    content=content,
                )

            return True

        except Exception as e:
            log_debug(f"EntityMemoryStore._asave_entity failed: {e}")
            return False

    # =========================================================================
    # Background Extraction
    # =========================================================================

    def _extract_and_save(
        self,
        messages: List[Any],
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> None:
        """Extract entities from messages (sync)."""
        if not self.model or not self.db:
            return

        try:
            conversation_text = self._messages_to_text(messages=messages)

            tools = self._get_extraction_tools(
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=namespace,
            )

            functions = self._build_functions_for_model(tools=tools)

            messages_for_model = [
                self._get_extraction_system_message(),
                {"role": "user", "content": f"Extract entities from this conversation:\n\n{conversation_text}"},
            ]

            model_copy = deepcopy(self.model)
            response = model_copy.response(
                messages=messages_for_model,
                tools=functions,
            )

            if response.tool_executions:
                self.entity_updated = True
                log_debug("EntityMemoryStore: Extraction saved entities")

        except Exception as e:
            log_warning(f"EntityMemoryStore._extract_and_save failed: {e}")

    async def _aextract_and_save(
        self,
        messages: List[Any],
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> None:
        """Extract entities from messages (async)."""
        if not self.model or not self.db:
            return

        try:
            conversation_text = self._messages_to_text(messages=messages)

            tools = self._get_async_extraction_tools(
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=namespace,
            )

            functions = self._build_functions_for_model(tools=tools)

            messages_for_model = [
                self._get_extraction_system_message(),
                {"role": "user", "content": f"Extract entities from this conversation:\n\n{conversation_text}"},
            ]

            model_copy = deepcopy(self.model)
            response = await model_copy.aresponse(
                messages=messages_for_model,
                tools=functions,
            )

            if response.tool_executions:
                self.entity_updated = True
                log_debug("EntityMemoryStore: Extraction saved entities")

        except Exception as e:
            log_warning(f"EntityMemoryStore._aextract_and_save failed: {e}")

    def _get_extraction_system_message(self) -> Dict[str, str]:
        """Get system message for extraction."""
        custom_instructions = self.config.instructions or ""
        additional = self.config.additional_instructions or ""

        if self.config.system_message:
            return {"role": "system", "content": self.config.system_message}

        content = dedent("""\
            You are an Entity Extractor. Identify people, companies, projects,
            and other notable entities mentioned in conversations.

            ## Entity Structure

            Entities have:
            - **Core**: entity_id (lowercase_underscores), entity_type, name, description, properties
            - **Facts**: Timeless truths (semantic memory) - "Uses PostgreSQL", "Based in SF"
            - **Events**: Time-bound occurrences (episodic memory) - "Launched v2 on Jan 15"
            - **Relationships**: Connections to other entities - "Bob is CEO of Acme"

            ## What to Extract

            Extract entities that are:
            - Mentioned by name (people, companies, products, projects)
            - Important to the conversation context
            - Likely to be referenced again

            ## What NOT to Extract

            - The user themselves (that's UserProfile, not EntityMemory)
            - Generic concepts without specific identifiers
            - One-off mentions unlikely to recur

            ## Guidelines

            - Use lowercase_underscore entity_ids (e.g., "acme_corp", "bob_smith")
            - Choose appropriate entity_type (person, company, project, product, system, etc.)
            - Capture factual information as facts
            - Capture time-specific events with dates when known
            - Capture relationships between entities when mentioned
            - Be concise but complete
            - It's fine to extract nothing if no notable entities are mentioned

        """)

        if custom_instructions:
            content += f"\n{custom_instructions}\n"

        if additional:
            content += f"\n{additional}\n"

        return {"role": "system", "content": content}

    def _get_extraction_tools(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> List[Callable]:
        """Get sync extraction tools based on config."""
        tools = []
        effective_namespace = namespace or self.config.namespace

        if self.config.enable_create_entity:

            def create_entity(
                entity_id: str,
                entity_type: str,
                name: str,
                description: Optional[str] = None,
            ) -> str:
                """Create a new entity."""
                success = self.create_entity(
                    entity_id=entity_id,
                    entity_type=entity_type,
                    name=name,
                    description=description,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    namespace=effective_namespace,
                )
                return f"Created: {entity_type}/{entity_id}" if success else "Entity exists"

            tools.append(create_entity)

        if self.config.enable_add_fact:

            def add_fact(entity_id: str, entity_type: str, fact: str) -> str:
                """Add a fact to an entity."""
                fact_id = self.add_fact(
                    entity_id=entity_id,
                    entity_type=entity_type,
                    fact=fact,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    namespace=effective_namespace,
                )
                return f"Fact added: {fact_id}" if fact_id else "Entity not found"

            tools.append(add_fact)

        if self.config.enable_add_event:

            def add_event(
                entity_id: str,
                entity_type: str,
                event: str,
                date: Optional[str] = None,
            ) -> str:
                """Add an event to an entity."""
                event_id = self.add_event(
                    entity_id=entity_id,
                    entity_type=entity_type,
                    event=event,
                    date=date,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    namespace=effective_namespace,
                )
                return f"Event added: {event_id}" if event_id else "Entity not found"

            tools.append(add_event)

        if self.config.enable_add_relationship:

            def add_relationship(
                entity_id: str,
                entity_type: str,
                related_entity_id: str,
                relation: str,
            ) -> str:
                """Add a relationship between entities."""
                rel_id = self.add_relationship(
                    entity_id=entity_id,
                    entity_type=entity_type,
                    related_entity_id=related_entity_id,
                    relation=relation,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    namespace=effective_namespace,
                )
                return f"Relationship added: {rel_id}" if rel_id else "Entity not found"

            tools.append(add_relationship)

        return tools

    def _get_async_extraction_tools(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> List[Callable]:
        """Get async extraction tools based on config."""
        tools = []
        effective_namespace = namespace or self.config.namespace

        if self.config.enable_create_entity:

            async def create_entity(
                entity_id: str,
                entity_type: str,
                name: str,
                description: Optional[str] = None,
            ) -> str:
                """Create a new entity."""
                success = await self.acreate_entity(
                    entity_id=entity_id,
                    entity_type=entity_type,
                    name=name,
                    description=description,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    namespace=effective_namespace,
                )
                return f"Created: {entity_type}/{entity_id}" if success else "Entity exists"

            tools.append(create_entity)

        if self.config.enable_add_fact:

            async def add_fact(entity_id: str, entity_type: str, fact: str) -> str:
                """Add a fact to an entity."""
                fact_id = await self.aadd_fact(
                    entity_id=entity_id,
                    entity_type=entity_type,
                    fact=fact,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    namespace=effective_namespace,
                )
                return f"Fact added: {fact_id}" if fact_id else "Entity not found"

            tools.append(add_fact)

        if self.config.enable_add_event:

            async def add_event(
                entity_id: str,
                entity_type: str,
                event: str,
                date: Optional[str] = None,
            ) -> str:
                """Add an event to an entity."""
                event_id = await self.aadd_event(
                    entity_id=entity_id,
                    entity_type=entity_type,
                    event=event,
                    date=date,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    namespace=effective_namespace,
                )
                return f"Event added: {event_id}" if event_id else "Entity not found"

            tools.append(add_event)

        if self.config.enable_add_relationship:

            async def add_relationship(
                entity_id: str,
                entity_type: str,
                related_entity_id: str,
                relation: str,
            ) -> str:
                """Add a relationship between entities."""
                rel_id = await self.aadd_relationship(
                    entity_id=entity_id,
                    entity_type=entity_type,
                    related_entity_id=related_entity_id,
                    relation=relation,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    namespace=effective_namespace,
                )
                return f"Relationship added: {rel_id}" if rel_id else "Entity not found"

            tools.append(add_relationship)

        return tools

    def _build_functions_for_model(self, tools: List[Callable]) -> List[Any]:
        """Convert callables to Functions for model."""
        from agno.tools.function import Function

        functions = []
        seen_names = set()

        for tool in tools:
            try:
                name = tool.__name__
                if name in seen_names:
                    continue
                seen_names.add(name)

                func = Function.from_callable(tool, strict=True)
                func.strict = True
                functions.append(func)
            except Exception as e:
                log_warning(f"Could not add function {tool}: {e}")

        return functions

    def _messages_to_text(self, messages: List[Any]) -> str:
        """Convert messages to text for extraction."""
        parts = []
        for msg in messages:
            if msg.role == "user":
                content = msg.get_content_string() if hasattr(msg, "get_content_string") else str(msg.content)
                if content and content.strip():
                    parts.append(f"User: {content}")
            elif msg.role in ["assistant", "model"]:
                content = msg.get_content_string() if hasattr(msg, "get_content_string") else str(msg.content)
                if content and content.strip():
                    parts.append(f"Assistant: {content}")
        return "\n".join(parts)

    # =========================================================================
    # Private Helpers
    # =========================================================================

    def _build_entity_db_id(
        self,
        entity_id: str,
        entity_type: str,
        namespace: str,
    ) -> str:
        """Build unique DB ID for entity."""
        return f"entity_{namespace}_{entity_type}_{entity_id}"

    def _format_entity_basic(self, entity: Any) -> str:
        """Basic entity formatting fallback."""
        parts = []

        name = getattr(entity, "name", None)
        entity_type = getattr(entity, "entity_type", "unknown")
        entity_id = getattr(entity, "entity_id", "unknown")

        if name:
            parts.append(f"**{name}** ({entity_type})")
        else:
            parts.append(f"**{entity_id}** ({entity_type})")

        description = getattr(entity, "description", None)
        if description:
            parts.append(description)

        facts = getattr(entity, "facts", [])
        if facts:
            facts_text = "\n".join(f"  - {f.get('content', f)}" for f in facts[:5])
            parts.append(f"Facts:\n{facts_text}")

        return "\n".join(parts)

    def _format_entities_list(self, entities: List[EntityMemory]) -> str:
        """Format entities for tool output."""
        parts = []
        for i, entity in enumerate(entities, 1):
            if hasattr(entity, "get_context_text"):
                formatted = entity.get_context_text()
            else:
                formatted = self._format_entity_basic(entity=entity)
            parts.append(f"{i}. {formatted}")
        return "\n\n".join(parts)

    # =========================================================================
    # Representation
    # =========================================================================

    def __repr__(self) -> str:
        """String representation for debugging."""
        has_db = self.db is not None
        has_model = self.model is not None
        return (
            f"EntityMemoryStore("
            f"mode={self.config.mode.value}, "
            f"namespace={self.config.namespace}, "
            f"db={has_db}, "
            f"model={has_model}, "
            f"enable_agent_tools={self.config.enable_agent_tools})"
        )
