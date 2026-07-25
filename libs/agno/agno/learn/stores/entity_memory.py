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

The agent surface is four tools:
- remember_about: upsert an entity with facts, events and an optional note pointer
- link_entities: record a relationship between two entities
- search_entities: search stored entities, or list them by recency
- forget: retire a fact, or archive a whole entity

Scoping:
- entity_id: derived in the store from the entity's name (slugified)
- entity_type: category (e.g., "company", "person", "project", "product")
- namespace: sharing scope:
    - "user": Private to current user
    - "global": Shared with everyone (default)
    - "<custom>": Custom grouping (e.g., "sales_team")

Supported Modes:
- AGENTIC only. The agent records entities through tools; there is no
  extraction pass. This mirrors how session_context documents itself as
  ALWAYS-only.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from os import getenv
from textwrap import dedent
from typing import Any, Callable, Dict, List, Optional, Tuple, Union, cast

from agno.learn.config import EntityMemoryConfig, LearningMode
from agno.learn.schemas import EntityMemory
from agno.learn.stores.protocol import LearningStore
from agno.learn.utils import build_learning_id
from agno.utils.log import (
    log_debug,
    log_info,
    log_warning,
    set_log_level_to_debug,
    set_log_level_to_info,
)

try:
    from agno.db.base import AsyncBaseDb, BaseDb
except ImportError:
    pass


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _slugify(name: str) -> str:
    """Derive a stable entity_id from a display name: lowercase, underscores."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return slug or name.strip().lower()


def _slugify_or_none(name: Optional[str]) -> Optional[str]:
    """Slugify, returning None when the name carries no usable identity."""
    if not name or not name.strip():
        return None
    return _slugify(name) or None


def _normalize_fact_text(text: str) -> str:
    """Fold case and collapse whitespace for fact matching."""
    return re.sub(r"\s+", " ", text.strip().casefold())


# =============================================================================
# Tool docstrings (shared between the sync and async tool variants)
# =============================================================================

_REMEMBER_ABOUT_DOC = """Record something about an entity - a person, project, company, system, or product.

Upserts: the entity is created if new, merged into if already known. Refer to the
entity by name ("Sarah Chen", "radar") - never invent an id.

What goes where:
- facts: one-line current values you expect to be replaced ("db: Postgres - see note").
- events: things that happened on a date ("shipped v1 on 2026-07-20"). Positions and
  opinions are events, not facts.
- note: the path of the note file holding the detail this entity indexes
  (e.g. "notes/radar.md"). Set it whenever the content lives in a note.

Args:
    entity: The entity's name as people say it (e.g. "Sarah Chen", "radar").
    entity_type: Category: person, project, company, system, product - or another short noun.
    description: One-line description of what this entity is.
    facts: One-line facts to record on the entity.
    events: Dated occurrences to record.
    note: Path of the note file with the full detail (e.g. "notes/radar.md").

Returns:
    Confirmation of what was recorded.
"""

_LINK_ENTITIES_DOC = """Link two entities with a relationship ("Sarah Chen" works_on "radar").

Both ends are resolved by name. An end that is not known yet is created as a
minimal entity, so it is safe to link first and describe later. The link is
stored on both entities, so it is visible from either side.

Args:
    entity: Source entity name.
    relation: The relationship, a short verb phrase ("works_on", "owns", "uses").
    related_entity: Target entity name.

Returns:
    Confirmation of the recorded link.
"""

_SEARCH_ENTITIES_DOC = """Search stored entities, or list them.

With a query, matches entity names, facts, events and relationships. Without a
query, lists entities by recency - use that to browse what exists ("who works on
what"). Results include each entity's note path; follow it with read_file when you
need the detail behind an indexed line.

Args:
    query: Text to match (a name, a fact fragment). Omit to list entities by recency.
    entity_type: Optional filter: person, project, company, system, product, etc.

Returns:
    Matching entities with their facts, events and relationships, or a listing.
"""

_FORGET_DOC = """Retire a fact from an entity, or archive the whole entity.

With fact: retires the matching fact - it stops being recalled, nothing is deleted.
Without fact: archives the entity. An archived entity leaves recall and the entity
directory, stays findable via search_entities, and any later remember_about about
it revives it.

Args:
    entity: The entity's name.
    fact: The fact to retire, worded as closely as you can to how it was stored.

Returns:
    Confirmation of what was retired or archived.
"""


@dataclass
class EntityMemoryStore(LearningStore):
    """Storage backend for Entity Memory learning type.

    Stores knowledge about external entities with three types of memory:
    - **Facts**: Semantic memory - current truths about the entity
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
    _degraded_search_logged: bool = field(default=False, init=False)

    def __post_init__(self):
        self._schema = self.config.schema or EntityMemory

        if self.config.mode != LearningMode.AGENTIC:
            raise ValueError(
                f"EntityMemoryStore is AGENTIC-only: the agent records entities through its tools "
                f"and there is no extraction pass. Remove mode={self.config.mode.value!r} from "
                f"EntityMemoryConfig or set LearningMode.AGENTIC."
            )

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

        Archived entities are excluded from recall (they stay reachable via search).

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
        if effective_namespace == "user" and not user_id:
            log_warning("EntityMemoryStore.recall: namespace='user' requires user_id")
            return None

        entity = self.get(
            entity_id=entity_id,
            entity_type=entity_type,
            user_id=user_id,
            namespace=effective_namespace,
        )
        if entity is not None and getattr(entity, "archived_at", None):
            return None
        return entity

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
        if effective_namespace == "user" and not user_id:
            log_warning("EntityMemoryStore.arecall: namespace='user' requires user_id")
            return None

        entity = await self.aget(
            entity_id=entity_id,
            entity_type=entity_type,
            user_id=user_id,
            namespace=effective_namespace,
        )
        if entity is not None and getattr(entity, "archived_at", None):
            return None
        return entity

    def process(self, messages: List[Any], **kwargs) -> None:
        """No-op: entity memory is AGENTIC-only, capture happens through the tools."""
        return

    async def aprocess(self, messages: List[Any], **kwargs) -> None:
        """Async version of process (no-op)."""
        return

    def build_context(self, data: Any) -> str:
        """Build context for the agent.

        Formats entity memory for injection into the agent's system prompt.

        Args:
            data: Entity memory data from recall() - single entity or list.

        Returns:
            Context string to inject into the agent's system prompt.
        """
        if not data:
            if self._should_expose_tools:
                return dedent("""\
                    <entity_memory_system>
                    You have entity memory - a knowledge base about the people, companies,
                    projects, systems and products relevant to your work.

                    **Available Tools:**
                    - `remember_about`: Record facts, events, a description or a note pointer on an entity
                    - `link_entities`: Record a relationship between two entities
                    - `search_entities`: Find stored entities, or list them by recency
                    - `forget`: Retire a fact, or archive an entity

                    **When to use entity memory:**
                    - You learn something substantive about a company, person, or project
                    - Information would be useful to recall in future conversations
                    - A stored fact turns out to be wrong or obsolete (state the new fact;
                      supersession retires the old one)
                    </entity_memory_system>""")
            return ""

        # Handle single entity or list
        entities = data if isinstance(data, list) else [data]
        if not entities:
            return ""

        formatted_parts = []
        for entity in entities:
            if hasattr(entity, "get_context_text"):
                formatted_parts.append(entity.get_context_text())
            else:
                formatted_parts.append(self._format_entity_basic(entity=entity))

        formatted = "\n\n---\n\n".join(formatted_parts)

        context = dedent(f"""\
            <entity_memory>
            **Known information about relevant entities:**

            {formatted}

            <entity_memory_guidelines>
            Use this knowledge naturally in your responses:
            - Reference stored facts without citing "entity memory"
            - Treat this as background knowledge you simply have
            - Current conversation takes precedence if there's conflicting information
            - Record new substantive information with remember_about
            </entity_memory_guidelines>
        """)

        context += "</entity_memory>"

        return context

    def get_tools(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
        **kwargs,
    ) -> List[Callable]:
        """Get the four agent tools (sync variants).

        Args:
            user_id: User context (for "user" namespace scoping).
            agent_id: Agent context (stored for audit).
            team_id: Team context (stored for audit).
            namespace: Default namespace for operations.
            **kwargs: Additional context (ignored).

        Returns:
            List of callable tools (empty if enable_agent_tools=False).
        """
        if not self._should_expose_tools:
            return []
        return self._build_agent_tools(
            async_mode=False,
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
        """Async version of get_tools: the same four tools as async callables."""
        if not self._should_expose_tools:
            return []
        return self._build_agent_tools(
            async_mode=True,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            namespace=namespace,
        )

    @property
    def was_updated(self) -> bool:
        """Check if entity was updated in last operation."""
        return self.entity_updated

    @property
    def _should_expose_tools(self) -> bool:
        """Whether the four tools are exposed to the agent."""
        return self.config.enable_agent_tools

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def db(self) -> Optional[Union["BaseDb", "AsyncBaseDb"]]:
        """Database backend."""
        return self.config.db

    @property
    def model(self):
        """Model for the fact-supersession judgment."""
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
    # Agent Tools (one factory generates the sync and async variants)
    # =========================================================================

    def _build_agent_tools(
        self,
        async_mode: bool,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> List[Callable]:
        """Build the four agent tools, closing over the run's identity context.

        The sync and async variants share their docstrings (the model-facing
        contract) and both delegate to the store's public write methods.
        """
        store = self
        effective_namespace = namespace or self.config.namespace

        if async_mode:

            async def remember_about(
                entity: str,
                entity_type: str,
                description: Optional[str] = None,
                facts: List[str] = [],
                events: List[str] = [],
                note: Optional[str] = None,
            ) -> str:
                return await store.aremember_about(
                    entity=entity,
                    entity_type=entity_type,
                    description=description,
                    facts=facts,
                    events=events,
                    note=note,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    namespace=effective_namespace,
                )

            async def link_entities(entity: str, relation: str, related_entity: str) -> str:
                return await store.alink_entities(
                    entity=entity,
                    relation=relation,
                    related_entity=related_entity,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    namespace=effective_namespace,
                )

            async def search_entities(query: Optional[str] = None, entity_type: Optional[str] = None) -> str:
                return await store.asearch_entities(
                    query=query,
                    entity_type=entity_type,
                    user_id=user_id,
                    namespace=effective_namespace,
                )

            async def forget(entity: str, fact: Optional[str] = None) -> str:
                return await store.aforget(
                    entity=entity,
                    fact=fact,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    namespace=effective_namespace,
                )
        else:

            def remember_about(  # type: ignore[misc]
                entity: str,
                entity_type: str,
                description: Optional[str] = None,
                facts: List[str] = [],
                events: List[str] = [],
                note: Optional[str] = None,
            ) -> str:
                return store.remember_about(
                    entity=entity,
                    entity_type=entity_type,
                    description=description,
                    facts=facts,
                    events=events,
                    note=note,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    namespace=effective_namespace,
                )

            def link_entities(entity: str, relation: str, related_entity: str) -> str:  # type: ignore[misc]
                return store.link_entities(
                    entity=entity,
                    relation=relation,
                    related_entity=related_entity,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    namespace=effective_namespace,
                )

            def search_entities(  # type: ignore[misc]
                query: Optional[str] = None, entity_type: Optional[str] = None
            ) -> str:
                return store.search_entities(
                    query=query,
                    entity_type=entity_type,
                    user_id=user_id,
                    namespace=effective_namespace,
                )

            def forget(entity: str, fact: Optional[str] = None) -> str:  # type: ignore[misc]
                return store.forget(
                    entity=entity,
                    fact=fact,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    namespace=effective_namespace,
                )

        remember_about.__doc__ = _REMEMBER_ABOUT_DOC
        link_entities.__doc__ = _LINK_ENTITIES_DOC
        search_entities.__doc__ = _SEARCH_ENTITIES_DOC
        forget.__doc__ = _FORGET_DOC

        return [remember_about, link_entities, search_entities, forget]

    # =========================================================================
    # Public write API: remember_about
    # =========================================================================

    def remember_about(
        self,
        entity: str,
        entity_type: str,
        description: Optional[str] = None,
        facts: Optional[List[str]] = None,
        events: Optional[List[str]] = None,
        note: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> str:
        """Upsert an entity by name: create it if new, merge into it if known.

        Returns:
            A confirmation message describing what was recorded.
        """
        if not self.db:
            return "Entity memory has no database configured; nothing was recorded."
        if not _slugify_or_none(entity):
            return "Entity name is required; nothing was recorded."

        effective_namespace = namespace or self.config.namespace
        if effective_namespace == "user" and not user_id:
            log_warning("EntityMemoryStore.remember_about: namespace='user' requires user_id")
            return "Entity memory needs a user_id for the 'user' namespace; nothing was recorded."

        existing = self._resolve(
            entity=entity,
            entity_type=entity_type,
            user_id=user_id,
            namespace=effective_namespace,
        )

        entity_obj, created, revived = self._apply_remember(
            existing=existing,
            entity=entity,
            entity_type=entity_type,
            description=description,
            facts=facts or [],
            events=events or [],
            note=note,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            namespace=effective_namespace,
        )

        saved = self._save_entity(
            entity=entity_obj,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            namespace=effective_namespace,
        )
        if not saved:
            return f"Failed to record on {entity_obj.entity_type}/{entity_obj.entity_id}."

        self.entity_updated = True
        return self._remember_message(
            entity_obj, created=created, revived=revived, facts=facts or [], events=events or [], note=note
        )

    async def aremember_about(
        self,
        entity: str,
        entity_type: str,
        description: Optional[str] = None,
        facts: Optional[List[str]] = None,
        events: Optional[List[str]] = None,
        note: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> str:
        """Async version of remember_about."""
        if not self.db:
            return "Entity memory has no database configured; nothing was recorded."
        if not _slugify_or_none(entity):
            return "Entity name is required; nothing was recorded."

        effective_namespace = namespace or self.config.namespace
        if effective_namespace == "user" and not user_id:
            log_warning("EntityMemoryStore.aremember_about: namespace='user' requires user_id")
            return "Entity memory needs a user_id for the 'user' namespace; nothing was recorded."

        existing = await self._aresolve(
            entity=entity,
            entity_type=entity_type,
            user_id=user_id,
            namespace=effective_namespace,
        )

        entity_obj, created, revived = self._apply_remember(
            existing=existing,
            entity=entity,
            entity_type=entity_type,
            description=description,
            facts=facts or [],
            events=events or [],
            note=note,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            namespace=effective_namespace,
        )

        saved = await self._asave_entity(
            entity=entity_obj,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            namespace=effective_namespace,
        )
        if not saved:
            return f"Failed to record on {entity_obj.entity_type}/{entity_obj.entity_id}."

        self.entity_updated = True
        return self._remember_message(
            entity_obj, created=created, revived=revived, facts=facts or [], events=events or [], note=note
        )

    def _apply_remember(
        self,
        existing: Optional[EntityMemory],
        entity: str,
        entity_type: str,
        description: Optional[str],
        facts: List[str],
        events: List[str],
        note: Optional[str],
        user_id: Optional[str],
        agent_id: Optional[str],
        team_id: Optional[str],
        namespace: str,
    ) -> Tuple[EntityMemory, bool, bool]:
        """Create or merge the entity in memory. Returns (entity, created, revived)."""
        now = _utc_now_iso()
        created = False
        revived = False

        if existing is None:
            created = True
            entity_obj = self.schema(
                entity_id=_slugify(entity),
                entity_type=entity_type,
                name=entity.strip(),
                description=description,
                properties={},
                facts=[],
                events=[],
                relationships=[],
                namespace=namespace,
                user_id=user_id if namespace == "user" else None,
                agent_id=agent_id,
                team_id=team_id,
                created_at=now,
                updated_at=now,
            )
        else:
            entity_obj = existing
            if description is not None:
                entity_obj.description = description
            if getattr(entity_obj, "archived_at", None):
                entity_obj.archived_at = None
                revived = True
                log_info(
                    f"EntityMemoryStore: entity {entity_obj.entity_type}/{entity_obj.entity_id} "
                    f"was archived and has been revived by this write."
                )

        for fact in facts:
            if fact and fact.strip():
                entity_obj.add_fact(fact)
        for event in events:
            if event and event.strip():
                entity_obj.add_event(event)
        if note is not None and note.strip():
            entity_obj.properties = {**(entity_obj.properties or {}), "note": note.strip()}

        entity_obj.updated_at = now
        return entity_obj, created, revived

    def _remember_message(
        self,
        entity_obj: EntityMemory,
        created: bool,
        revived: bool,
        facts: List[str],
        events: List[str],
        note: Optional[str],
    ) -> str:
        label = f"{entity_obj.entity_type}/{entity_obj.entity_id}"
        verb = "Created" if created else "Updated"
        parts = []
        if facts:
            parts.append(f"{len(facts)} fact(s)")
        if events:
            parts.append(f"{len(events)} event(s)")
        if note:
            parts.append(f"note pointer {note}")
        recorded = f" Recorded {', '.join(parts)}." if parts else ""
        revived_text = " The entity was archived and is now revived." if revived else ""
        return f"{verb} {label}.{recorded}{revived_text}"

    # =========================================================================
    # Public write API: link_entities
    # =========================================================================

    def link_entities(
        self,
        entity: str,
        relation: str,
        related_entity: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> str:
        """Record a relationship between two entities, resolving both ends by name.

        An end that does not resolve is created as a minimal entity with
        entity_type="unknown"; a later remember_about with a real type merges it.
        The edge is written on both rows, each carrying the far end's resolved id,
        type, relation and direction.
        """
        if not self.db:
            return "Entity memory has no database configured; nothing was recorded."

        effective_namespace = namespace or self.config.namespace
        if effective_namespace == "user" and not user_id:
            log_warning("EntityMemoryStore.link_entities: namespace='user' requires user_id")
            return "Entity memory needs a user_id for the 'user' namespace; nothing was recorded."

        if not _slugify_or_none(entity) or not _slugify_or_none(related_entity):
            return "Both entity names are required; nothing was recorded."

        source = self._resolve_or_create_minimal(
            entity, user_id=user_id, agent_id=agent_id, team_id=team_id, namespace=effective_namespace
        )
        target = self._resolve_or_create_minimal(
            related_entity, user_id=user_id, agent_id=agent_id, team_id=team_id, namespace=effective_namespace
        )
        if source.entity_id == target.entity_id and source.entity_type == target.entity_type:
            return f"Cannot link {source.entity_type}/{source.entity_id} to itself; nothing was recorded."

        self._write_edge(source=source, target=target, relation=relation)

        for entity_obj in (source, target):
            if not self._save_entity(
                entity=entity_obj,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=effective_namespace,
            ):
                return "Failed to record the link."

        self.entity_updated = True
        return self._link_message(source=source, relation=relation, target=target)

    async def alink_entities(
        self,
        entity: str,
        relation: str,
        related_entity: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> str:
        """Async version of link_entities."""
        if not self.db:
            return "Entity memory has no database configured; nothing was recorded."

        effective_namespace = namespace or self.config.namespace
        if effective_namespace == "user" and not user_id:
            log_warning("EntityMemoryStore.alink_entities: namespace='user' requires user_id")
            return "Entity memory needs a user_id for the 'user' namespace; nothing was recorded."

        if not _slugify_or_none(entity) or not _slugify_or_none(related_entity):
            return "Both entity names are required; nothing was recorded."

        source = await self._aresolve_or_create_minimal(
            entity, user_id=user_id, agent_id=agent_id, team_id=team_id, namespace=effective_namespace
        )
        target = await self._aresolve_or_create_minimal(
            related_entity, user_id=user_id, agent_id=agent_id, team_id=team_id, namespace=effective_namespace
        )
        if source.entity_id == target.entity_id and source.entity_type == target.entity_type:
            return f"Cannot link {source.entity_type}/{source.entity_id} to itself; nothing was recorded."

        self._write_edge(source=source, target=target, relation=relation)

        for entity_obj in (source, target):
            if not await self._asave_entity(
                entity=entity_obj,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=effective_namespace,
            ):
                return "Failed to record the link."

        self.entity_updated = True
        return self._link_message(source=source, relation=relation, target=target)

    def _write_edge(self, source: EntityMemory, target: EntityMemory, relation: str) -> None:
        """Write the edge on both rows, each carrying the far end's id and type."""
        now = _utc_now_iso()
        source.add_relationship(
            related_entity_id=target.entity_id,
            relation=relation,
            direction="outgoing",
            entity_type=target.entity_type,
        )
        source.updated_at = now
        target.add_relationship(
            related_entity_id=source.entity_id,
            relation=relation,
            direction="incoming",
            entity_type=source.entity_type,
        )
        target.updated_at = now

    def _link_message(self, source: EntityMemory, relation: str, target: EntityMemory) -> str:
        return (
            f"Linked {source.entity_type}/{source.entity_id} --[{relation}]--> {target.entity_type}/{target.entity_id}."
        )

    # =========================================================================
    # Public read API: search_entities (agent-facing, formatted)
    # =========================================================================

    def search_entities(
        self,
        query: Optional[str] = None,
        entity_type: Optional[str] = None,
        user_id: Optional[str] = None,
        namespace: Optional[str] = None,
        limit: int = 10,
    ) -> str:
        """Search stored entities (or list them by recency) and format the results."""
        effective_namespace = namespace or self.config.namespace
        if effective_namespace == "user" and not user_id:
            log_warning("EntityMemoryStore.search_entities: namespace='user' requires user_id")
            return "Entity memory needs a user_id for the 'user' namespace; nothing was searched."

        if query:
            results = self.search(
                query=query,
                entity_type=entity_type,
                user_id=user_id,
                namespace=effective_namespace,
                limit=limit,
                include_archived=True,
            )
        else:
            results = self.list_entities(
                entity_type=entity_type,
                user_id=user_id,
                namespace=effective_namespace,
                limit=limit,
                include_archived=True,
            )

        return self._format_search_results(
            entities=results,
            query=query,
            entity_type=entity_type,
            namespace=effective_namespace,
            limit=limit,
        )

    async def asearch_entities(
        self,
        query: Optional[str] = None,
        entity_type: Optional[str] = None,
        user_id: Optional[str] = None,
        namespace: Optional[str] = None,
        limit: int = 10,
    ) -> str:
        """Async version of search_entities."""
        effective_namespace = namespace or self.config.namespace
        if effective_namespace == "user" and not user_id:
            log_warning("EntityMemoryStore.asearch_entities: namespace='user' requires user_id")
            return "Entity memory needs a user_id for the 'user' namespace; nothing was searched."

        if query:
            results = await self.asearch(
                query=query,
                entity_type=entity_type,
                user_id=user_id,
                namespace=effective_namespace,
                limit=limit,
                include_archived=True,
            )
        else:
            results = await self.alist_entities(
                entity_type=entity_type,
                user_id=user_id,
                namespace=effective_namespace,
                limit=limit,
                include_archived=True,
            )

        return self._format_search_results(
            entities=results,
            query=query,
            entity_type=entity_type,
            namespace=effective_namespace,
            limit=limit,
        )

    def _format_search_results(
        self,
        entities: List[EntityMemory],
        query: Optional[str],
        entity_type: Optional[str],
        namespace: str,
        limit: int,
    ) -> str:
        scope = f"namespace '{namespace}'"
        if entity_type:
            scope += f", type '{entity_type}'"

        if not entities:
            if query:
                return f"No entities matching {query!r} (searched {scope})."
            return f"No entities stored yet (searched {scope})."

        parts = []
        for i, entity in enumerate(entities, 1):
            parts.append(f"{i}. {self._format_entity_hit(entity)}")

        header = (
            f"Found {len(entities)} entity/entities matching {query!r} in {scope}"
            if query
            else f"{len(entities)} most recently updated entity/entities in {scope}"
        )
        footer = ""
        if len(entities) >= limit:
            footer = f"\n\nShowing the first {limit}; narrow the query or entity_type to see others."
        return f"{header}:\n\n" + "\n\n".join(parts) + footer

    def _format_entity_hit(self, entity: EntityMemory, max_facts: int = 6, max_events: int = 3) -> str:
        """Format one search hit: bounded, with truncation markers and the note path."""
        name = getattr(entity, "name", None) or entity.entity_id
        archived = " (archived)" if getattr(entity, "archived_at", None) else ""
        lines = [f"**{name}** ({entity.entity_type}){archived}"]

        description = getattr(entity, "description", None)
        if description:
            lines.append(description)

        properties = getattr(entity, "properties", {}) or {}
        note = properties.get("note")
        if note:
            lines.append(f"note: {note}")
        other_props = {k: v for k, v in properties.items() if k != "note"}
        if other_props:
            lines.append("Properties: " + ", ".join(f"{k}: {v}" for k, v in other_props.items()))

        live = entity.live_facts() if hasattr(entity, "live_facts") else getattr(entity, "facts", [])
        if live:
            shown = live[:max_facts]
            marker = f" ({len(shown)} of {len(live)} facts)" if len(live) > len(shown) else ""
            lines.append("Facts:" + marker)
            for f in shown:
                lines.append(f"  - {f.get('content', f) if isinstance(f, dict) else f}")

        entity_events = getattr(entity, "events", []) or []
        if entity_events:
            shown_events = entity_events[-max_events:]
            marker = (
                f" (last {len(shown_events)} of {len(entity_events)} events)"
                if len(entity_events) > len(shown_events)
                else ""
            )
            lines.append("Events:" + marker)
            for e in shown_events:
                if isinstance(e, dict):
                    date = f" ({e.get('date')})" if e.get("date") else ""
                    lines.append(f"  - {e.get('content', e)}{date}")
                else:
                    lines.append(f"  - {e}")

        relationships = getattr(entity, "relationships", []) or []
        if relationships:
            lines.append("Relationships:")
            for r in relationships:
                if isinstance(r, dict):
                    arrow = "->" if r.get("direction", "outgoing") == "outgoing" else "<-"
                    lines.append(f"  - {r.get('relation')} {arrow} {r.get('entity_id')}")

        return "\n".join(lines)

    # =========================================================================
    # Public write API: forget
    # =========================================================================

    def forget(
        self,
        entity: str,
        fact: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> str:
        """Retire a fact from an entity, or archive the whole entity."""
        if not self.db:
            return "Entity memory has no database configured; nothing was changed."

        effective_namespace = namespace or self.config.namespace
        if effective_namespace == "user" and not user_id:
            log_warning("EntityMemoryStore.forget: namespace='user' requires user_id")
            return "Entity memory needs a user_id for the 'user' namespace; nothing was changed."
        entity_obj = self._resolve(entity=entity, entity_type=None, user_id=user_id, namespace=effective_namespace)
        if entity_obj is None:
            return f"No entity found matching {entity!r}."

        result, should_save = self._apply_forget(entity_obj=entity_obj, fact=fact)
        if should_save:
            saved = self._save_entity(
                entity=entity_obj,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=effective_namespace,
            )
            if not saved:
                return f"Failed to update {entity_obj.entity_type}/{entity_obj.entity_id}."
            self.entity_updated = True
        return result

    async def aforget(
        self,
        entity: str,
        fact: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> str:
        """Async version of forget."""
        if not self.db:
            return "Entity memory has no database configured; nothing was changed."

        effective_namespace = namespace or self.config.namespace
        if effective_namespace == "user" and not user_id:
            log_warning("EntityMemoryStore.aforget: namespace='user' requires user_id")
            return "Entity memory needs a user_id for the 'user' namespace; nothing was changed."
        entity_obj = await self._aresolve(
            entity=entity, entity_type=None, user_id=user_id, namespace=effective_namespace
        )
        if entity_obj is None:
            return f"No entity found matching {entity!r}."

        result, should_save = self._apply_forget(entity_obj=entity_obj, fact=fact)
        if should_save:
            saved = await self._asave_entity(
                entity=entity_obj,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=effective_namespace,
            )
            if not saved:
                return f"Failed to update {entity_obj.entity_type}/{entity_obj.entity_id}."
            self.entity_updated = True
        return result

    def _retire(self, entity_obj: EntityMemory, fact: Dict[str, Any], superseded_by: str = "forgotten") -> None:
        """Retire a fact dict in place, tolerating records without an id."""
        fact_id = fact.get("id")
        if fact_id:
            entity_obj.retire_fact(fact_id, superseded_by=superseded_by)
        else:
            fact["superseded_at"] = _utc_now_iso()
            fact["superseded_by"] = superseded_by

    def _apply_forget(self, entity_obj: EntityMemory, fact: Optional[str]) -> Tuple[str, bool]:
        """Apply forget in memory. Returns (message, should_save)."""
        label = f"{entity_obj.entity_type}/{entity_obj.entity_id}"

        # No fact: archive the entity.
        if fact is None or not fact.strip():
            if getattr(entity_obj, "archived_at", None):
                return f"{label} is already archived.", False
            entity_obj.archived_at = _utc_now_iso()
            entity_obj.updated_at = _utc_now_iso()
            return (
                f"Archived {label}. It will no longer be recalled; search_entities can still "
                f"find it, and any new remember_about about it revives it.",
                True,
            )

        # Fact given: match against live fact content.
        needle = _normalize_fact_text(fact)
        live = entity_obj.live_facts()

        exact = [f for f in live if isinstance(f, dict) and _normalize_fact_text(str(f.get("content", ""))) == needle]
        if exact:
            for f in exact:
                self._retire(entity_obj, f)
            entity_obj.updated_at = _utc_now_iso()
            return f"Retired fact on {label}: {exact[0].get('content')}", True

        contains = [
            f
            for f in live
            if isinstance(f, dict)
            and (
                needle in _normalize_fact_text(str(f.get("content", "")))
                or _normalize_fact_text(str(f.get("content", ""))) in needle
            )
        ]
        if len(contains) == 1:
            self._retire(entity_obj, contains[0])
            entity_obj.updated_at = _utc_now_iso()
            return f"Retired fact on {label}: {contains[0].get('content')}", True
        if len(contains) > 1:
            listing = "\n".join(f"  - {f.get('content')}" for f in contains)
            return (
                f"Multiple facts on {label} match {fact!r}; nothing was retired. "
                f"Call forget again with the exact wording of one of:\n{listing}",
                False,
            )

        if not live:
            return f"No matching fact on {label}. It has no live facts.", False
        bounded = live[:10]
        listing = "\n".join(f"  - {f.get('content') if isinstance(f, dict) else f}" for f in bounded)
        more = f"\n  ... and {len(live) - len(bounded)} more" if len(live) > len(bounded) else ""
        return f"No matching fact on {label}. Its live facts are:\n{listing}{more}", False

    # =========================================================================
    # Resolution (name -> stored entity)
    # =========================================================================

    def _resolve(
        self,
        entity: str,
        entity_type: Optional[str],
        user_id: Optional[str],
        namespace: str,
    ) -> Optional[EntityMemory]:
        """Resolve an entity by name within the namespace.

        Matches the slugified name against stored entity ids. When entity_type is
        given, that exact key is tried first; otherwise (and as a fallback) the id
        is matched across types.
        """
        slug = _slugify(entity)

        if entity_type:
            found = self.get(entity_id=slug, entity_type=entity_type, user_id=user_id, namespace=namespace)
            if found is not None:
                return found

        rows = self._get_rows_by_entity_id(entity_id=slug, user_id=user_id, namespace=namespace)
        for row in rows:
            parsed = self.schema.from_dict(row.get("content"))
            if parsed is not None:
                return parsed
        return None

    async def _aresolve(
        self,
        entity: str,
        entity_type: Optional[str],
        user_id: Optional[str],
        namespace: str,
    ) -> Optional[EntityMemory]:
        """Async version of _resolve."""
        slug = _slugify(entity)

        if entity_type:
            found = await self.aget(entity_id=slug, entity_type=entity_type, user_id=user_id, namespace=namespace)
            if found is not None:
                return found

        rows = await self._aget_rows_by_entity_id(entity_id=slug, user_id=user_id, namespace=namespace)
        for row in rows:
            parsed = self.schema.from_dict(row.get("content"))
            if parsed is not None:
                return parsed
        return None

    def _resolve_or_create_minimal(
        self,
        entity: str,
        user_id: Optional[str],
        agent_id: Optional[str],
        team_id: Optional[str],
        namespace: str,
    ) -> EntityMemory:
        """Resolve an entity by name, creating a minimal 'unknown' entity if absent."""
        found = self._resolve(entity=entity, entity_type=None, user_id=user_id, namespace=namespace)
        if found is not None:
            return found
        return self._minimal_entity(
            entity=entity, user_id=user_id, agent_id=agent_id, team_id=team_id, namespace=namespace
        )

    async def _aresolve_or_create_minimal(
        self,
        entity: str,
        user_id: Optional[str],
        agent_id: Optional[str],
        team_id: Optional[str],
        namespace: str,
    ) -> EntityMemory:
        """Async version of _resolve_or_create_minimal."""
        found = await self._aresolve(entity=entity, entity_type=None, user_id=user_id, namespace=namespace)
        if found is not None:
            return found
        return self._minimal_entity(
            entity=entity, user_id=user_id, agent_id=agent_id, team_id=team_id, namespace=namespace
        )

    def _minimal_entity(
        self,
        entity: str,
        user_id: Optional[str],
        agent_id: Optional[str],
        team_id: Optional[str],
        namespace: str,
    ) -> EntityMemory:
        now = _utc_now_iso()
        return self.schema(
            entity_id=_slugify(entity),
            entity_type="unknown",
            name=entity.strip(),
            properties={},
            facts=[],
            events=[],
            relationships=[],
            namespace=namespace,
            user_id=user_id if namespace == "user" else None,
            agent_id=agent_id,
            team_id=team_id,
            created_at=now,
            updated_at=now,
        )

    def _get_rows_by_entity_id(self, entity_id: str, user_id: Optional[str], namespace: str) -> List[Dict[str, Any]]:
        """Fetch learnings rows for an entity id across entity types."""
        if not self.db:
            return []
        try:
            rows = self.db.get_learnings(
                learning_type=self.learning_type,
                entity_id=entity_id,
                namespace=namespace,
                user_id=user_id if namespace == "user" else None,
            )
            return self._order_rows(rows or [])
        except Exception as e:
            log_debug(f"EntityMemoryStore._get_rows_by_entity_id failed: {e}")
            return []

    async def _aget_rows_by_entity_id(
        self, entity_id: str, user_id: Optional[str], namespace: str
    ) -> List[Dict[str, Any]]:
        """Async version of _get_rows_by_entity_id."""
        if not self.db:
            return []
        try:
            if isinstance(self.db, AsyncBaseDb):
                rows = await self.db.get_learnings(
                    learning_type=self.learning_type,
                    entity_id=entity_id,
                    namespace=namespace,
                    user_id=user_id if namespace == "user" else None,
                )
            else:
                rows = self.db.get_learnings(
                    learning_type=self.learning_type,
                    entity_id=entity_id,
                    namespace=namespace,
                    user_id=user_id if namespace == "user" else None,
                )
            return self._order_rows(rows or [])
        except Exception as e:
            log_debug(f"EntityMemoryStore._aget_rows_by_entity_id failed: {e}")
            return []

    @staticmethod
    def _order_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Order rows newest-first with a deterministic tie-break on the id.

        Backend timestamps have second resolution, so same-second writes tie;
        resolution must not flip between such rows across calls.
        """
        return sorted(
            rows,
            key=lambda r: (-(r.get("updated_at") or r.get("created_at") or 0), str(r.get("learning_id") or "")),
        )

    # =========================================================================
    # Data API: get / list / search / delete
    # =========================================================================

    def get(
        self,
        entity_id: str,
        entity_type: str,
        user_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> Optional[EntityMemory]:
        """Retrieve entity by entity_id and entity_type.

        This is the keyed data API; it returns archived entities too.

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

            if result and result.get("content"):  # type: ignore[union-attr]
                return self.schema.from_dict(result["content"])  # type: ignore[index]

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

    def list_entities(
        self,
        entity_type: Optional[str] = None,
        user_id: Optional[str] = None,
        namespace: Optional[str] = None,
        limit: int = 10,
        include_archived: bool = False,
    ) -> List[EntityMemory]:
        """List entities by recency (most recently updated first)."""
        if not self.db:
            return []

        effective_namespace = namespace or self.config.namespace
        if effective_namespace == "user" and not user_id:
            log_warning("EntityMemoryStore.list_entities: namespace='user' requires user_id")
            return []

        try:
            results = self.db.get_learnings(
                learning_type=self.learning_type,
                entity_type=entity_type,
                namespace=effective_namespace,
                user_id=user_id if effective_namespace == "user" else None,
                limit=limit if include_archived else limit * 2,
            )
            return self._parse_rows(results or [], limit=limit, include_archived=include_archived)
        except Exception as e:
            log_debug(f"EntityMemoryStore.list_entities failed: {e}")
            return []

    async def alist_entities(
        self,
        entity_type: Optional[str] = None,
        user_id: Optional[str] = None,
        namespace: Optional[str] = None,
        limit: int = 10,
        include_archived: bool = False,
    ) -> List[EntityMemory]:
        """Async version of list_entities."""
        if not self.db:
            return []

        effective_namespace = namespace or self.config.namespace
        if effective_namespace == "user" and not user_id:
            log_warning("EntityMemoryStore.alist_entities: namespace='user' requires user_id")
            return []

        try:
            if isinstance(self.db, AsyncBaseDb):
                results = await self.db.get_learnings(
                    learning_type=self.learning_type,
                    entity_type=entity_type,
                    namespace=effective_namespace,
                    user_id=user_id if effective_namespace == "user" else None,
                    limit=limit if include_archived else limit * 2,
                )
            else:
                results = self.db.get_learnings(
                    learning_type=self.learning_type,
                    entity_type=entity_type,
                    namespace=effective_namespace,
                    user_id=user_id if effective_namespace == "user" else None,
                    limit=limit if include_archived else limit * 2,
                )
            return self._parse_rows(results or [], limit=limit, include_archived=include_archived)
        except Exception as e:
            log_debug(f"EntityMemoryStore.alist_entities failed: {e}")
            return []

    def _parse_rows(self, rows: List[Dict[str, Any]], limit: int, include_archived: bool) -> List[EntityMemory]:
        entities: List[EntityMemory] = []
        for row in rows:
            entity = self.schema.from_dict(row.get("content"))
            if entity is None:
                continue
            if not include_archived and getattr(entity, "archived_at", None):
                continue
            entities.append(entity)
            if len(entities) >= limit:
                break
        return entities

    def search(
        self,
        query: str,
        entity_type: Optional[str] = None,
        user_id: Optional[str] = None,
        namespace: Optional[str] = None,
        limit: int = 10,
        include_archived: bool = False,
    ) -> List[EntityMemory]:
        """Search for entities matching query.

        Routes through the db's server-side search_learnings; falls back to the
        client-side scan only when the backend does not implement it. Database
        errors from the server-side path are raised, never swallowed - a broken
        query must not present as an empty store.

        Args:
            query: Search query (matched against name, facts, events, etc.).
            entity_type: Filter by entity type.
            user_id: User ID for "user" namespace scoping.
            namespace: Filter by namespace.
            limit: Maximum results to return.
            include_archived: Include archived entities in results.

        Returns:
            List of matching EntityMemory objects.
        """
        if not self.db:
            return []

        effective_namespace = namespace or self.config.namespace
        if effective_namespace == "user" and not user_id:
            log_warning("EntityMemoryStore.search: namespace='user' requires user_id")
            return []

        try:
            rows = self.db.search_learnings(
                query=query,
                learning_type=self.learning_type,
                entity_type=entity_type,
                namespace=effective_namespace,
                user_id=user_id if effective_namespace == "user" else None,
                # Headroom for the client-side archived filter below.
                limit=limit if include_archived else limit * 2,
            )
        except (NotImplementedError, AttributeError):
            self._log_degraded_search_once()
            return self._search_client_side(
                query=query,
                entity_type=entity_type,
                user_id=user_id,
                namespace=effective_namespace,
                limit=limit,
                include_archived=include_archived,
            )

        entities = self._parse_rows(rows or [], limit=limit, include_archived=include_archived)
        log_debug(f"EntityMemoryStore.search: found {len(entities)} entities for query: {query[:50]}")
        return entities

    async def asearch(
        self,
        query: str,
        entity_type: Optional[str] = None,
        user_id: Optional[str] = None,
        namespace: Optional[str] = None,
        limit: int = 10,
        include_archived: bool = False,
    ) -> List[EntityMemory]:
        """Async version of search."""
        if not self.db:
            return []

        effective_namespace = namespace or self.config.namespace
        if effective_namespace == "user" and not user_id:
            log_warning("EntityMemoryStore.asearch: namespace='user' requires user_id")
            return []

        try:
            if isinstance(self.db, AsyncBaseDb):
                rows = await self.db.search_learnings(
                    query=query,
                    learning_type=self.learning_type,
                    entity_type=entity_type,
                    namespace=effective_namespace,
                    user_id=user_id if effective_namespace == "user" else None,
                    limit=limit if include_archived else limit * 2,
                )
            else:
                rows = self.db.search_learnings(
                    query=query,
                    learning_type=self.learning_type,
                    entity_type=entity_type,
                    namespace=effective_namespace,
                    user_id=user_id if effective_namespace == "user" else None,
                    limit=limit if include_archived else limit * 2,
                )
        except (NotImplementedError, AttributeError):
            self._log_degraded_search_once()
            return await self._asearch_client_side(
                query=query,
                entity_type=entity_type,
                user_id=user_id,
                namespace=effective_namespace,
                limit=limit,
                include_archived=include_archived,
            )

        entities = self._parse_rows(rows or [], limit=limit, include_archived=include_archived)
        log_debug(f"EntityMemoryStore.asearch: found {len(entities)} entities for query: {query[:50]}")
        return entities

    def _log_degraded_search_once(self) -> None:
        if not self._degraded_search_logged:
            self._degraded_search_logged = True
            log_warning(
                "EntityMemoryStore: this db backend has no search_learnings implementation; "
                "falling back to a client-side scan over the most recently updated rows. "
                "Search quality degrades as the store grows."
            )

    def _search_client_side(
        self,
        query: str,
        entity_type: Optional[str],
        user_id: Optional[str],
        namespace: str,
        limit: int,
        include_archived: bool,
    ) -> List[EntityMemory]:
        """Degraded fallback: over-fetch recent rows and substring-match in Python."""
        try:
            results = self.db.get_learnings(  # type: ignore[union-attr]
                learning_type=self.learning_type,
                entity_type=entity_type,
                namespace=namespace,
                user_id=user_id if namespace == "user" else None,
                limit=limit * 3,
            )
        except Exception as e:
            log_debug(f"EntityMemoryStore._search_client_side failed: {e}")
            return []
        return self._filter_rows_by_query(results or [], query=query, limit=limit, include_archived=include_archived)

    async def _asearch_client_side(
        self,
        query: str,
        entity_type: Optional[str],
        user_id: Optional[str],
        namespace: str,
        limit: int,
        include_archived: bool,
    ) -> List[EntityMemory]:
        """Async version of _search_client_side."""
        try:
            if isinstance(self.db, AsyncBaseDb):
                results = await self.db.get_learnings(
                    learning_type=self.learning_type,
                    entity_type=entity_type,
                    namespace=namespace,
                    user_id=user_id if namespace == "user" else None,
                    limit=limit * 3,
                )
            else:
                results = self.db.get_learnings(  # type: ignore[union-attr]
                    learning_type=self.learning_type,
                    entity_type=entity_type,
                    namespace=namespace,
                    user_id=user_id if namespace == "user" else None,
                    limit=limit * 3,
                )
        except Exception as e:
            log_debug(f"EntityMemoryStore._asearch_client_side failed: {e}")
            return []
        return self._filter_rows_by_query(results or [], query=query, limit=limit, include_archived=include_archived)

    def _filter_rows_by_query(
        self, rows: List[Dict[str, Any]], query: str, limit: int, include_archived: bool
    ) -> List[EntityMemory]:
        entities: List[EntityMemory] = []
        query_lower = query.lower()
        for row in rows:
            content = row.get("content", {})
            if not self._matches_query(content=content, query=query_lower):
                continue
            entity = self.schema.from_dict(content)
            if entity is None:
                continue
            if not include_archived and getattr(entity, "archived_at", None):
                continue
            entities.append(entity)
            if len(entities) >= limit:
                break
        return entities

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

    def delete(
        self,
        entity_id: str,
        entity_type: str,
        namespace: Optional[str] = None,
    ) -> bool:
        """Hard-delete an entity from the store (data API - not exposed as a tool)."""
        if not self.db:
            return False

        effective_namespace = namespace or self.config.namespace
        try:
            return bool(
                self.db.delete_learning(id=self._build_entity_db_id(entity_id, entity_type, effective_namespace))
            )
        except Exception as e:
            log_debug(f"EntityMemoryStore.delete failed: {e}")
            return False

    async def adelete(
        self,
        entity_id: str,
        entity_type: str,
        namespace: Optional[str] = None,
    ) -> bool:
        """Async version of delete."""
        if not self.db:
            return False

        effective_namespace = namespace or self.config.namespace
        try:
            if isinstance(self.db, AsyncBaseDb):
                return bool(
                    await self.db.delete_learning(
                        id=self._build_entity_db_id(entity_id, entity_type, effective_namespace)
                    )
                )
            return bool(
                self.db.delete_learning(id=self._build_entity_db_id(entity_id, entity_type, effective_namespace))
            )
        except Exception as e:
            log_debug(f"EntityMemoryStore.adelete failed: {e}")
            return False

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
    # Private Helpers
    # =========================================================================

    def _build_entity_db_id(
        self,
        entity_id: str,
        entity_type: str,
        namespace: str,
    ) -> str:
        """Build unique DB ID for entity."""
        return cast(
            str,
            build_learning_id("entity_memory", entity_id=entity_id, entity_type=entity_type, namespace=namespace),
        )

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

    def print(
        self,
        entity_id: str,
        entity_type: str,
        *,
        user_id: Optional[str] = None,
        namespace: Optional[str] = None,
        raw: bool = False,
    ) -> None:
        """Print formatted entity memory.

        Args:
            entity_id: The entity to print.
            entity_type: Type of entity.
            user_id: User ID for "user" namespace scoping.
            namespace: Namespace to search in.
            raw: If True, print raw dict using pprint instead of formatted panel.
        """
        from agno.learn.utils import print_panel

        effective_namespace = namespace or self.config.namespace

        entity = self.get(
            entity_id=entity_id,
            entity_type=entity_type,
            user_id=user_id,
            namespace=effective_namespace,
        )

        lines = []

        if entity:
            # Header: name and type
            name = getattr(entity, "name", None)
            etype = getattr(entity, "entity_type", entity_type)
            header = f"[bold]{name or entity_id}[/bold] ({etype})"
            if getattr(entity, "archived_at", None):
                header += " [dim](archived)[/dim]"
            lines.append(header)

            # Description
            description = getattr(entity, "description", None)
            if description:
                lines.append(description)

            # Properties
            properties = getattr(entity, "properties", {})
            if properties:
                lines.append("")
                lines.append("Properties:")
                for key, value in properties.items():
                    lines.append(f"  {key}: {value}")

            # Facts (live only)
            live = entity.live_facts() if hasattr(entity, "live_facts") else getattr(entity, "facts", [])
            if live:
                lines.append("")
                lines.append("Facts:")
                for fact in live:
                    if isinstance(fact, dict):
                        fact_id = fact.get("id", "?")
                        content = fact.get("content", str(fact))
                    else:
                        fact_id = "?"
                        content = str(fact)
                    lines.append(f"  [dim]\\[{fact_id}][/dim] {content}")

            # Events
            events = getattr(entity, "events", [])
            if events:
                lines.append("")
                lines.append("Events:")
                for event in events:
                    if isinstance(event, dict):
                        event_id = event.get("id", "?")
                        content = event.get("content", str(event))
                        date = event.get("date")
                        date_str = f" ({date})" if date else ""
                    else:
                        event_id = "?"
                        content = str(event)
                        date_str = ""
                    lines.append(f"  [dim]\\[{event_id}][/dim] {content}{date_str}")

            # Relationships
            relationships = getattr(entity, "relationships", [])
            if relationships:
                lines.append("")
                lines.append("Relationships:")
                for rel in relationships:
                    if isinstance(rel, dict):
                        related_id = rel.get("entity_id", "?")
                        relation = rel.get("relation", "related_to")
                        direction = rel.get("direction", "outgoing")
                        if direction == "outgoing":
                            lines.append(f"  {relation} → {related_id}")
                        else:
                            lines.append(f"  {relation} ← {related_id}")

        print_panel(
            title="Entity Memory",
            subtitle=f"{entity_type}/{entity_id}",
            lines=lines,
            empty_message="No entity found",
            raw_data=entity,
            raw=raw,
        )
