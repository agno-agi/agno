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
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple, Union, cast
from weakref import WeakKeyDictionary

from agno.learn.config import EntityMemoryConfig, LearningMode
from agno.learn.schemas import EntityMemory
from agno.learn.stores.protocol import LearningStore
from agno.learn.utils import build_learning_id, values_match_query
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


# Symbols that name a thing rather than separate words. Without these, "C++"
# and "C#" both key to `c` and merge into "C" - a wrong merge, and there is no
# unmerge.
_IDENTITY_SYMBOLS = {"++": "plus_plus", "+": "plus", "#": "sharp"}


def _slugify(name: str) -> str:
    """Derive a stable entity_id from a display name: lowercase, underscores.

    Accented letters fold to their base letter first, so Anna Müller and Anna
    Möller keep distinct ids while "Sofia Munoz" still resolves to the
    "Sofía Muñoz" already on file.

    Letters that survive the fold are KEPT, whatever their script. Dropping
    them meant a name only partly Latin lost the half that identified it -
    "李 Ming" keyed to `ming` and merged with an unrelated Ming, the same
    no-unmerge corruption the fold exists to prevent.

    A few symbols carry identity rather than punctuation: C, C++ and C# are
    three languages, and collapsing every non-word character made them one
    entity holding all three's facts, with the discarded names written
    nowhere. Those spell themselves out; the rest still collapse, so
    "Acme, Inc." and "Acme Inc" stay one company.
    """
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", name.strip().lower())
    folded = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    for symbol, word in _IDENTITY_SYMBOLS.items():
        folded = folded.replace(symbol, f"_{word}_")
    slug = re.sub(r"[^\w]+", "_", folded, flags=re.UNICODE).strip("_")
    return slug or name.strip().lower()


def _slugify_or_none(name: Optional[str]) -> Optional[str]:
    """Slugify, returning None when the name carries no usable identity.

    Pure-punctuation names ("???", "%") are rejected; non-ASCII names pass
    through (the ASCII slugifier cannot fold them, so the lowered name itself
    is the id).
    """
    if not name or not name.strip():
        return None
    slug = _slugify(name)
    if not slug or not re.search(r"[^\W_]", slug, re.UNICODE):
        return None
    return slug


def _normalize_fact_text(text: str) -> str:
    """Fold case and collapse whitespace for fact matching."""
    return re.sub(r"\s+", " ", text.strip().casefold())


def _normalize_name(name: str) -> str:
    """Fold case and collapse whitespace for name and alias matching."""
    return re.sub(r"\s+", " ", name.strip().casefold())


_MESSAGE_STOPWORDS = frozenset(
    """a an and are as at be been but by can could did do does for from had has have how i if in into is it its me my
    of on or our she so that the their them then there they this to was we were what when where which who why will
    with would you your about tell know new more some any all just like get make said says told asked shall
    please show give need want us him her his hers ours yours theirs also very much many still over after before
    between should must may might each other than too not no yes ok okay let lets going go went come came thing
    things something anything everything nothing someone anyone everyone whats hows whos""".split()
)


def _message_terms(message: str, max_terms: int = 8) -> List[str]:
    """Distinctive lexical terms of a message, for relevance recall.

    Deliberately lexical (no semantic retrieval, per the non-goals): lowercase
    word tokens, minus stopwords and short words, deduplicated in order.
    """
    terms: List[str] = []
    for word in re.findall(r"[\w][\w\-']*", message.lower()):
        if len(word) < 3 or word in _MESSAGE_STOPWORDS:
            continue
        if word not in terms:
            terms.append(word)
        if len(terms) >= max_terms:
            break
    return terms


# The DB key is entity_{namespace}_{entity_type}_{entity_id}, so type drift
# splits entities exactly like name drift: "person" on Monday and "people" on
# Friday is two Sarahs. Fold case and singularize against this canonical list;
# anything else passes through lowercased.
_CANONICAL_ENTITY_TYPES = frozenset({"person", "project", "company", "system", "product"})
# The placeholder link_entities mints for an endpoint it has never been told
# about; it is the one type that merges into a real one.
_UNKNOWN_ENTITY_TYPE = "unknown"
_IRREGULAR_ENTITY_TYPES = {"people": "person", "persons": "person", "companies": "company"}


def _normalize_entity_type(entity_type: Optional[str]) -> Optional[str]:
    if entity_type is None or not entity_type.strip():
        return entity_type
    normalized = re.sub(r"\s+", "_", entity_type.strip().lower())
    if normalized in _CANONICAL_ENTITY_TYPES:
        return normalized
    if normalized in _IRREGULAR_ENTITY_TYPES:
        return _IRREGULAR_ENTITY_TYPES[normalized]
    if normalized.endswith("s") and normalized[:-1] in _CANONICAL_ENTITY_TYPES:
        return normalized[:-1]
    return normalized


def _blank_to_none(value: Optional[str]) -> Optional[str]:
    """Blank string in, ``None`` out.

    Models fill unused optional arguments with "" rather than omitting them
    (a strict tool schema has no way to say "absent"), so a blank argument
    means "not supplied". Passed through, it would become a filter that
    matches nothing and read as an honest "not found".
    """
    if value is None:
        return None
    return value.strip() or None


def _split_qualified_name(entity: str, known_types: Sequence[str]) -> Tuple[str, Optional[str]]:
    """Split a "type/name" reference into (name, type).

    Two entities can share a name under different types, and neither
    link_entities nor forget carries an entity_type; the ambiguity replies tell
    the model to name one as "project/Harbor", so both tools read it back.

    Only a prefix that actually names one of the stored types counts. A name
    containing a slash is far more likely to be a name - "AC/DC" is a band, not
    a DC of type AC - and treating it as qualified sends resolution to a key
    the write path never uses.
    """
    if "/" not in entity:
        return entity, None
    prefix, _, rest = entity.partition("/")
    prefix, rest = prefix.strip(), rest.strip()
    if not prefix or not rest:
        return entity, None
    if _normalize_entity_type(prefix) not in {_normalize_entity_type(t) for t in known_types}:
        return entity, None
    return rest, prefix


def _mentions(needle: str, term: str) -> bool:
    """Whether ``needle`` names ``term`` as a whole word.

    Plain containment let a longer far-end name swallow a shorter one:
    "designed_by -> Sarah Chen" matched the edge to `sarah` as well, and the
    qualified form the refusal then asks for could not break the tie either,
    because "person/sarah" is itself a substring of "person/sarah_chen". The
    link became unretireable, which is the one thing forget exists to prevent.
    """
    return re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", needle) is not None


def _slug_phrase_in(needle: str, term_slug: str) -> bool:
    """Whether the needle names an entity whose slug is ``term_slug``.

    The context block renders a far end's DISPLAY name, and a name is not
    recoverable from its slug once the slug has folded an accent, a hyphen or
    an ampersand: "supplier_is -> Café Noir" is the wording the docstring asks
    for and `cafe_noir` is what the edge stores. Slugify both and compare on
    token boundaries.
    """
    needle_tokens = [t for t in _slugify(needle).split("_") if t]
    term_tokens = [t for t in term_slug.split("_") if t]
    if not term_tokens or len(term_tokens) > len(needle_tokens):
        return False
    return any(
        needle_tokens[i : i + len(term_tokens)] == term_tokens for i in range(len(needle_tokens) - len(term_tokens) + 1)
    )


def _types_can_merge(incoming: Optional[str], existing: Optional[str]) -> bool:
    """Whether a name match across two entity types is the same thing.

    Only the ``unknown`` placeholder ``link_entities`` mints merges across
    types - describing it later is what gives it a real type. Two named types
    are two things: Atlas the system is not Atlas the team, and a merge has no
    unmerge. Models coin types freely, so restricting this to a canonical list
    left the common case (``team``, ``framework``, ``service``) merging.

    Fragmenting is the recoverable failure here - both rows render, and the
    write path says when a same-name sibling exists so the model can correct
    itself.
    """
    incoming_type = _normalize_entity_type(incoming)
    existing_type = _normalize_entity_type(existing)
    if not incoming_type or not existing_type or incoming_type == existing_type:
        return True
    return _UNKNOWN_ENTITY_TYPE in (incoming_type, existing_type)


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

A link that stops being true is removed with forget, naming it the way it is
rendered ("written_in -> Rust"); recording the new one does not retire the old.

Args:
    entity: Source entity name. If two entities share it, name one as
        "project/Harbor" - the reply tells you when that is needed.
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

_SUPERSESSION_SYSTEM_PROMPT = """You judge fact supersession for an entity's memory.

You are given the entity's live facts (each with an id) and newly stated facts.
Identify which OLD facts the new facts contradict or replace.

A new fact supersedes an old one when both cannot be true at the same time - a
changed value, a corrected status, a reversed decision - or when the new fact is
a direct update of the same attribute. Related but compatible facts do NOT
supersede each other.

Call mark_superseded exactly once with the ids of the superseded old facts and
your confidence (0.0 to 1.0) for each, as parallel lists. If nothing is
superseded, call it with two empty lists. Be conservative: when unsure, do not
supersede - a wrong supersession hides information the user gave us.
"""


_FORGET_DOC = """Retire a fact or a relationship from an entity, or archive the whole entity.

With fact: retires the matching fact - it stops being recalled, nothing is deleted.
A relationship is retired the same way, naming it as it is rendered
("written_in -> Rust"): use this when a link is no longer true, because stating
the new link does not remove the old one.
Without fact: archives the entity. An archived entity leaves recall and the entity
directory, stays findable via search_entities, and any later remember_about about
it revives it.

Args:
    entity: The entity's name. If two entities share it, name one as
        "project/Harbor" - the reply tells you when that is needed.
    fact: The fact to retire, worded as closely as you can to how it was stored,
        or the relationship to remove ("works_on -> radar").

Returns:
    Confirmation of what was retired, removed or archived.
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
    _async_db_in_sync_logged: bool = field(default=False, init=False)
    # Every write here is a read-modify-write over a whole row, and an
    # assistant turn's tool calls run concurrently (models/base.py gathers
    # them), so two tools touching one entity would overwrite each other and
    # both report success. Writes take this lock; reads and the judge's
    # provider call stay outside it. Keyed weakly by event loop - see
    # _write_lock.
    _async_write_locks: Any = field(default_factory=WeakKeyDictionary, init=False)

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
        message: Optional[str] = None,
        **kwargs,
    ) -> Optional[Any]:
        """Retrieve entity memory for context injection.

        Always returns the entity directory (name + type, newest first,
        archived excluded) so the agent can see what exists and ground its
        negatives - "not in the directory" is a fact, "substring didn't match"
        is not. With a message, the top-k relevant entities come back expanded:
        entities whose name or alias appears in the message, then (still under
        k) entities matched by a bounded lexical search over the message's
        distinctive terms. A keyed lookup (entity_id + entity_type) stays
        available and is expanded first. Archived entities are excluded from
        recall (they stay reachable via search).

        Args:
            entity_id: Optional entity to expand (with entity_type).
            entity_type: The type of entity (with entity_id).
            user_id: User ID for "user" namespace scoping.
            namespace: Filter by namespace.
            message: The current message; drives relevance recall.
            **kwargs: Additional context (ignored).

        Returns:
            Dict with "directory" (all known entities, bounded), "entities"
            (the expanded ones) and "related_names" (the one-hop name map), or
            None when the namespace cannot be read.
        """
        effective_namespace = namespace or self.config.namespace
        if effective_namespace == "user" and not user_id:
            log_warning("EntityMemoryStore.recall: namespace='user' requires user_id")
            return None

        # One row beyond the cap, so a truncated directory is distinguishable
        # from one that happens to be exactly at the cap.
        directory = self.list_entities(
            user_id=user_id,
            namespace=effective_namespace,
            limit=self.config.max_entities_in_directory + 1,
        )

        entities: List[EntityMemory] = []
        if entity_id and entity_type:
            entity = self.get(
                entity_id=entity_id,
                entity_type=entity_type,
                user_id=user_id,
                namespace=effective_namespace,
            )
            if entity is not None and not getattr(entity, "archived_at", None):
                entities.append(entity)

        if message:
            top_k = self.config.max_entities_in_context
            entities = self._merge_relevant(entities, self._match_directory_by_message(directory, message), top_k)
            if len(entities) < top_k:
                # All selected terms are searched and merged round-robin, so a
                # generic first term cannot consume the budget before the
                # distinctive one.
                term_results = [
                    self.search(query=term, user_id=user_id, namespace=effective_namespace, limit=top_k)
                    for term in self._terms_to_search(message, entities)
                ]
                entities = self._merge_relevant(entities, self._interleave(term_results), top_k)

        related_names = self._related_names(
            entities=entities, directory=directory, user_id=user_id, namespace=effective_namespace
        )
        return {"directory": directory, "entities": entities, "related_names": related_names}

    async def arecall(
        self,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        user_id: Optional[str] = None,
        namespace: Optional[str] = None,
        message: Optional[str] = None,
        **kwargs,
    ) -> Optional[Any]:
        """Async version of recall."""
        effective_namespace = namespace or self.config.namespace
        if effective_namespace == "user" and not user_id:
            log_warning("EntityMemoryStore.arecall: namespace='user' requires user_id")
            return None

        directory = await self.alist_entities(
            user_id=user_id,
            namespace=effective_namespace,
            limit=self.config.max_entities_in_directory + 1,
        )

        entities: List[EntityMemory] = []
        if entity_id and entity_type:
            entity = await self.aget(
                entity_id=entity_id,
                entity_type=entity_type,
                user_id=user_id,
                namespace=effective_namespace,
            )
            if entity is not None and not getattr(entity, "archived_at", None):
                entities.append(entity)

        if message:
            top_k = self.config.max_entities_in_context
            entities = self._merge_relevant(entities, self._match_directory_by_message(directory, message), top_k)
            if len(entities) < top_k:
                term_results = []
                for term in self._terms_to_search(message, entities):
                    term_results.append(
                        await self.asearch(query=term, user_id=user_id, namespace=effective_namespace, limit=top_k)
                    )
                entities = self._merge_relevant(entities, self._interleave(term_results), top_k)

        related_names = await self._arelated_names(
            entities=entities, directory=directory, user_id=user_id, namespace=effective_namespace
        )
        return {"directory": directory, "entities": entities, "related_names": related_names}

    @staticmethod
    def _match_directory_by_message(directory: List[EntityMemory], message: str) -> List[EntityMemory]:
        """Directory entries whose name or alias appears in the message.

        Word-boundary matched: a two-letter entity named "Al" must not match
        "always" and evict the entity the turn is actually about.
        """
        normalized_message = _normalize_name(message)
        matched: List[EntityMemory] = []
        for entity in directory:
            names = [getattr(entity, "name", None) or ""] + list(getattr(entity, "aliases", None) or [])
            for candidate in names:
                if not candidate:
                    continue
                pattern = r"(?<!\w)" + re.escape(_normalize_name(candidate)) + r"(?!\w)"
                if re.search(pattern, normalized_message):
                    matched.append(entity)
                    break
        return matched

    @staticmethod
    def _interleave(result_lists: List[List[EntityMemory]]) -> List[EntityMemory]:
        """Round-robin merge, so one term's results cannot starve another's."""
        merged: List[EntityMemory] = []
        index = 0
        while True:
            advanced = False
            for results in result_lists:
                if index < len(results):
                    merged.append(results[index])
                    advanced = True
            if not advanced:
                return merged
            index += 1

    @staticmethod
    def _merge_relevant(current: List[EntityMemory], additions: List[EntityMemory], top_k: int) -> List[EntityMemory]:
        merged = list(current)
        seen = {(e.entity_id, e.entity_type) for e in merged}
        for entity in additions:
            key = (entity.entity_id, entity.entity_type)
            if key in seen:
                continue
            if getattr(entity, "archived_at", None):
                continue
            seen.add(key)
            merged.append(entity)
            if len(merged) >= top_k:
                break
        return merged[: max(top_k, 0)]

    @staticmethod
    def _terms_to_search(message: str, already_matched: List[EntityMemory], max_searches: int = 3) -> List[str]:
        """Message terms worth a bounded lexical search.

        Terms whose token already appears in a matched entity's name are
        skipped; the rest are ordered proper-noun-ish first (capitalized
        mid-sentence in the original message - the strongest name signal),
        then by length, so a generic early word cannot consume the search
        budget before the distinctive one.
        """
        covered_tokens: set = set()
        for e in already_matched:
            covered_tokens.update(_normalize_name(getattr(e, "name", None) or e.entity_id).split())

        capitalized = {match.group(0).lower() for match in re.finditer(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-z]+", message)}
        terms = [t for t in _message_terms(message) if t not in covered_tokens]
        terms.sort(key=lambda t: (t not in capitalized, -len(t)))
        return terms[:max_searches]

    def _related_names(
        self,
        entities: List[EntityMemory],
        directory: List[EntityMemory],
        user_id: Optional[str],
        namespace: str,
        max_lookups: int = 10,
    ) -> Dict[str, str]:
        """One-hop link expansion: the display names of the entities the
        expanded entities link to. Names come from the already-fetched
        directory where possible; the remainder is a bounded set of keyed
        lookups (no recursion, no content)."""
        name_map = {
            e.entity_id: (getattr(e, "name", None) or e.entity_id) for e in directory if getattr(e, "entity_id", None)
        }
        missing = self._missing_link_targets(entities=entities, known=name_map)
        for far_id, far_type in missing[:max_lookups]:
            far = self.get(entity_id=far_id, entity_type=far_type, user_id=user_id, namespace=namespace)
            if far is None:
                # The edge's stored type can go stale (unknown -> real upgrade);
                # resolve the id across types before giving up on the name.
                for row in self._get_rows_by_entity_id(entity_id=far_id, user_id=user_id, namespace=namespace):
                    far = self.schema.from_dict(row.get("content"))
                    if far is not None:
                        break
            if far is not None:
                name = getattr(far, "name", None) or far_id
                if getattr(far, "archived_at", None):
                    name += " (archived)"
                name_map[far_id] = name
        return name_map

    async def _arelated_names(
        self,
        entities: List[EntityMemory],
        directory: List[EntityMemory],
        user_id: Optional[str],
        namespace: str,
        max_lookups: int = 10,
    ) -> Dict[str, str]:
        """Async version of _related_names."""
        name_map = {
            e.entity_id: (getattr(e, "name", None) or e.entity_id) for e in directory if getattr(e, "entity_id", None)
        }
        missing = self._missing_link_targets(entities=entities, known=name_map)
        for far_id, far_type in missing[:max_lookups]:
            far = await self.aget(entity_id=far_id, entity_type=far_type, user_id=user_id, namespace=namespace)
            if far is None:
                for row in await self._aget_rows_by_entity_id(entity_id=far_id, user_id=user_id, namespace=namespace):
                    far = self.schema.from_dict(row.get("content"))
                    if far is not None:
                        break
            if far is not None:
                name = getattr(far, "name", None) or far_id
                if getattr(far, "archived_at", None):
                    name += " (archived)"
                name_map[far_id] = name
        return name_map

    @staticmethod
    def _missing_link_targets(entities: List[EntityMemory], known: Dict[str, str]) -> List[Tuple[str, str]]:
        missing: List[Tuple[str, str]] = []
        seen = set(known)
        for entity in entities:
            for rel in getattr(entity, "relationships", None) or []:
                if not isinstance(rel, dict):
                    continue
                far_id = rel.get("entity_id")
                far_type = rel.get("entity_type")
                if far_id and far_type and far_id not in seen:
                    seen.add(far_id)
                    missing.append((far_id, far_type))
        return missing

    def process(self, messages: List[Any], **kwargs) -> None:
        """No-op: entity memory is AGENTIC-only, capture happens through the tools."""
        return

    async def aprocess(self, messages: List[Any], **kwargs) -> None:
        """Async version of process (no-op)."""
        return

    def build_context(self, data: Any) -> str:
        """Build context for the agent.

        Formats entity memory for injection into the agent's system prompt:
        the entity directory first (always, when anything exists), then the
        expanded entities, bounded by the config's rendering knobs.

        Args:
            data: Data from recall() - the {"directory", "entities"} dict, or a
                single entity / list of entities from direct calls.

        Returns:
            Context string to inject into the agent's system prompt.
        """
        directory: List[EntityMemory] = []
        entities: List[Any] = []
        related_names: Dict[str, str] = {}
        if isinstance(data, dict) and "directory" in data:
            directory = data.get("directory") or []
            entities = data.get("entities") or []
            related_names = data.get("related_names") or {}
        elif data:
            entities = data if isinstance(data, list) else [data]

        if not directory and not entities:
            if self._should_expose_tools:
                return dedent("""\
                    <entity_memory>
                    No entities recorded yet.
                    </entity_memory>""")
            return ""

        sections: List[str] = []

        directory_truncated = False
        if directory:
            cap = self.config.max_entities_in_directory
            directory_truncated = len(directory) > cap
            listed = directory[:cap]
            lines = []
            for entity in listed:
                name = getattr(entity, "name", None) or getattr(entity, "entity_id", "?")
                lines.append(f"- {name} ({getattr(entity, 'entity_type', '?')})")
            if directory_truncated:
                header = f"**Entity directory** (the {len(listed)} most recently updated entities; more exist)"
            else:
                header = "**Entity directory** (all known entities, newest first)"
            sections.append(header + ":\n" + "\n".join(lines))

        shown_entities = entities[: self.config.max_entities_in_context]
        if shown_entities:
            formatted_parts = []
            render_kwargs = {
                "max_facts": self.config.max_facts_per_entity,
                "max_events": self.config.max_events_per_entity,
                "related_names": related_names,
            }
            for entity in shown_entities:
                render = getattr(entity, "get_context_text", None)
                if callable(render):
                    # A custom schema may define its own signature; pass only what
                    # it accepts (never re-invoke on error - side effects).
                    import inspect as _inspect

                    try:
                        params = _inspect.signature(render).parameters
                        has_var_kw = any(p.kind == p.VAR_KEYWORD for p in params.values())
                        accepted = {k: v for k, v in render_kwargs.items() if has_var_kw or k in params}
                    except (TypeError, ValueError):
                        accepted = {}
                    formatted_parts.append(render(**accepted))
                else:
                    formatted_parts.append(self._format_entity_basic(entity=entity))
            sections.append("**Known information about relevant entities:**\n\n" + "\n\n---\n\n".join(formatted_parts))

        body = "\n\n".join(sections)
        context = dedent("""\
            <entity_memory>
            {body}

            <entity_memory_guidelines>
            Use this knowledge naturally in your responses:
            - Reference stored facts without citing "entity memory"
            - Treat this as background knowledge you simply have
            - Current conversation takes precedence if there's conflicting information
            - {directory_line}
            </entity_memory_guidelines>
            </entity_memory>""").format(
            body=body,
            directory_line=(
                "The directory shows the most recently updated entities; use search_entities to check beyond it"
                if directory_truncated
                else "The directory is the full index: an entity not listed there is not known"
            ),
        )

        return context

    def instructions(self) -> str:
        """Agent-facing guidance for this store: the four tools and when to use them.

        Guidance only - the recalled entities and directory live in
        build_context().
        """
        if not self._should_expose_tools:
            return ""
        return dedent("""\
            <entity_memory_instructions>
            You have entity memory - a knowledge base about the people, companies,
            projects, systems and products relevant to your work.

            - `remember_about`: record facts, events, a description or a note pointer
              on an entity, by name. A correction is just the new fact: state it, and
              the contradicted old fact is retired automatically.
            - `link_entities`: record a relationship between two entities.
            - `search_entities`: find stored entities; with no query, list them by
              recency (the browse surface).
            - `forget`: retire a fact, or archive a whole entity.

            Record something whenever you learn substantive information about a
            company, person, project or system that future conversations will need.
            </entity_memory_instructions>""")

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
        aliases: Optional[List[str]] = None,
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

        # A blank optional argument means the model did not supply it, not that
        # it wants the stored value cleared - the tool surface has no way to
        # clear one, so treating "" as a value silently wipes a description or
        # a note pointer that a previous turn wrote.
        description = _blank_to_none(description)
        note = _blank_to_none(note)

        effective_namespace = namespace or self.config.namespace
        if effective_namespace == "user" and not user_id:
            log_warning("EntityMemoryStore.remember_about: namespace='user' requires user_id")
            return "Entity memory needs a user_id for the 'user' namespace; nothing was recorded."

        # The other three tools teach "project/Harbor" in their refusals and
        # docstrings, and the model uses it here too. Slugging it whole minted
        # project/project_harbor and stranded the correction on a phantom.
        entity, qualifier = self._qualified(
            entity=entity, user_id=user_id, namespace=effective_namespace, declared_type=entity_type
        )
        entity_type = qualifier or entity_type

        existing = self._resolve(
            entity=entity,
            entity_type=entity_type,
            user_id=user_id,
            namespace=effective_namespace,
        )

        novel_facts, duplicate_count = self._novel_facts(existing=existing, facts=facts or [])
        judgments = self._judge_superseded(existing=existing, new_facts=novel_facts)
        # The judge is a blocking provider call in the middle of a
        # read-modify-write over the whole row. Nothing else runs on this
        # thread meanwhile, but the background capture thread shares the store,
        # so merge onto the row as it stands now rather than the snapshot taken
        # before the call. The async twin holds a lock instead - there, an
        # assistant turn's tool calls really do interleave.
        existing = self._resolve(
            entity=entity,
            entity_type=entity_type,
            user_id=user_id,
            namespace=effective_namespace,
        )
        novel_facts, duplicate_count = self._novel_facts(existing=existing, facts=facts or [])

        entity_obj, created, revived, stale_row_key = self._apply_remember(
            existing=existing,
            entity=entity,
            entity_type=entity_type,
            description=description,
            facts=novel_facts,
            events=events or [],
            note=note,
            aliases=aliases,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            namespace=effective_namespace,
        )
        superseded_count = self._apply_supersessions(entity_obj=entity_obj, judgments=judgments, new_facts=novel_facts)

        saved = self._save_entity(
            entity=entity_obj,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            namespace=effective_namespace,
        )
        if not saved:
            return f"Failed to record on {entity_obj.entity_type}/{entity_obj.entity_id}."

        if stale_row_key:
            # The new row is saved; drop the old-typed row so the entity is not doubled.
            try:
                self.db.delete_learning(id=stale_row_key)
            except Exception as e:
                log_warning(f"EntityMemoryStore.remember_about: failed to delete stale row {stale_row_key}: {e}")
            self._repair_far_edge_types(
                entity_obj=entity_obj,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=effective_namespace,
            )

        self.entity_updated = True
        return self._remember_message(
            entity_obj,
            created=created,
            revived=revived,
            facts=novel_facts,
            events=events or [],
            note=note,
            superseded_count=superseded_count,
            duplicate_count=duplicate_count,
            siblings=self._same_name_siblings(
                entity_obj,
                self._get_rows_by_entity_id(
                    entity_id=entity_obj.entity_id, user_id=user_id, namespace=effective_namespace
                ),
            ),
        )

    async def aremember_about(
        self,
        entity: str,
        entity_type: str,
        description: Optional[str] = None,
        facts: Optional[List[str]] = None,
        events: Optional[List[str]] = None,
        note: Optional[str] = None,
        aliases: Optional[List[str]] = None,
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

        # A blank optional argument means the model did not supply it, not that
        # it wants the stored value cleared - the tool surface has no way to
        # clear one, so treating "" as a value silently wipes a description or
        # a note pointer that a previous turn wrote.
        description = _blank_to_none(description)
        note = _blank_to_none(note)

        effective_namespace = namespace or self.config.namespace
        if effective_namespace == "user" and not user_id:
            log_warning("EntityMemoryStore.aremember_about: namespace='user' requires user_id")
            return "Entity memory needs a user_id for the 'user' namespace; nothing was recorded."

        # See the sync twin: the qualified form the other tools teach.
        entity, qualifier = await self._aqualified(
            entity=entity, user_id=user_id, namespace=effective_namespace, declared_type=entity_type
        )
        entity_type = qualifier or entity_type

        existing = await self._aresolve(
            entity=entity,
            entity_type=entity_type,
            user_id=user_id,
            namespace=effective_namespace,
        )

        novel_facts, duplicate_count = self._novel_facts(existing=existing, facts=facts or [])
        # The judge's provider call stays outside the lock: it only reads.
        judgments = await self._ajudge_superseded(existing=existing, new_facts=novel_facts)

        async with self._write_lock():
            # Resolve again inside the lock. Everything above suspended - the
            # judge, and every db call on an async db - so a sibling tool call
            # from the same assistant turn may have created or changed this row
            # since. Merging onto the stale snapshot would overwrite it.
            existing = await self._aresolve(
                entity=entity,
                entity_type=entity_type,
                user_id=user_id,
                namespace=effective_namespace,
            )
            # Novelty has to be judged against the row we are about to merge
            # onto, not the pre-lock snapshot: a sibling call carrying the same
            # sentence would otherwise pass the duplicate check twice and
            # append it twice.
            novel_facts, duplicate_count = self._novel_facts(existing=existing, facts=facts or [])

            entity_obj, created, revived, stale_row_key = self._apply_remember(
                existing=existing,
                entity=entity,
                entity_type=entity_type,
                description=description,
                facts=novel_facts,
                events=events or [],
                note=note,
                aliases=aliases,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=effective_namespace,
            )
            superseded_count = self._apply_supersessions(
                entity_obj=entity_obj, judgments=judgments, new_facts=novel_facts
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

        if stale_row_key:
            # The new row is saved; drop the old-typed row so the entity is not doubled.
            try:
                if isinstance(self.db, AsyncBaseDb):
                    await self.db.delete_learning(id=stale_row_key)
                else:
                    self.db.delete_learning(id=stale_row_key)
            except Exception as e:
                log_warning(f"EntityMemoryStore.aremember_about: failed to delete stale row {stale_row_key}: {e}")
            await self._arepair_far_edge_types(
                entity_obj=entity_obj,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=effective_namespace,
            )

        self.entity_updated = True
        return self._remember_message(
            entity_obj,
            created=created,
            revived=revived,
            facts=novel_facts,
            events=events or [],
            note=note,
            superseded_count=superseded_count,
            duplicate_count=duplicate_count,
            siblings=self._same_name_siblings(
                entity_obj,
                await self._aget_rows_by_entity_id(
                    entity_id=entity_obj.entity_id, user_id=user_id, namespace=effective_namespace
                ),
            ),
        )

    def _novel_facts(self, existing: Optional[EntityMemory], facts: List[str]) -> Tuple[List[str], int]:
        """Drop blank facts and exact duplicates of the entity's live facts.

        Returns (novel_facts, duplicate_count). Recording the same sentence
        twice must not double it, and an exact duplicate needs no judgment.
        """
        cleaned = [f for f in facts if f and f.strip()]
        if existing is None:
            return cleaned, 0

        live_normalized = {
            _normalize_fact_text(str(f.get("content", ""))) for f in existing.live_facts() if isinstance(f, dict)
        }
        novel: List[str] = []
        duplicates = 0
        for f in cleaned:
            normalized = _normalize_fact_text(f)
            if normalized in live_normalized:
                duplicates += 1
                continue
            live_normalized.add(normalized)
            novel.append(f)
        return novel, duplicates

    # =========================================================================
    # Fact supersession (one judge call in the write path)
    # =========================================================================

    def _judge_superseded(self, existing: Optional[EntityMemory], new_facts: List[str]) -> List[Tuple[str, float]]:
        """One structured model call: which live facts do the new facts supersede?

        Skipped entirely when the entity is new, has no live facts, the write
        carries no facts, or no model is configured. Judge failures are
        conservative: nothing is superseded and the write proceeds.
        """
        if existing is None or not new_facts or self.model is None:
            return []
        live = [f for f in existing.live_facts() if isinstance(f, dict) and f.get("id")][-50:]
        if not live:
            return []

        try:
            from copy import deepcopy

            from agno.tools.function import Function

            captured: List[Tuple[str, float]] = []

            def mark_superseded(fact_ids: List[str], confidences: List[float] = []) -> str:
                """Mark which existing facts are superseded by the newly stated facts.

                Args:
                    fact_ids: The ids of the superseded existing facts. Empty if none.
                    confidences: Confidence (0.0-1.0) per id, in the same order.

                Returns:
                    Confirmation.
                """
                for fact_id, confidence in zip(fact_ids, confidences):
                    captured.append((str(fact_id), float(confidence)))
                return "Recorded."

            func = Function.from_callable(mark_superseded, strict=True)
            func.strict = True

            model_copy = deepcopy(self.model)
            model_copy.response(
                messages=self._build_supersession_messages(existing=existing, live=live, new_facts=new_facts),
                tools=[func],
                tool_call_limit=1,
            )
            return captured
        except Exception as e:
            log_warning(f"EntityMemoryStore: supersession judgment failed, keeping all facts: {e}")
            return []

    async def _ajudge_superseded(
        self, existing: Optional[EntityMemory], new_facts: List[str]
    ) -> List[Tuple[str, float]]:
        """Async version of _judge_superseded."""
        if existing is None or not new_facts or self.model is None:
            return []
        live = [f for f in existing.live_facts() if isinstance(f, dict) and f.get("id")][-50:]
        if not live:
            return []

        try:
            from copy import deepcopy

            from agno.tools.function import Function

            captured: List[Tuple[str, float]] = []

            def mark_superseded(fact_ids: List[str], confidences: List[float] = []) -> str:
                """Mark which existing facts are superseded by the newly stated facts.

                Args:
                    fact_ids: The ids of the superseded existing facts. Empty if none.
                    confidences: Confidence (0.0-1.0) per id, in the same order.

                Returns:
                    Confirmation.
                """
                for fact_id, confidence in zip(fact_ids, confidences):
                    captured.append((str(fact_id), float(confidence)))
                return "Recorded."

            func = Function.from_callable(mark_superseded, strict=True)
            func.strict = True

            model_copy = deepcopy(self.model)
            await model_copy.aresponse(
                messages=self._build_supersession_messages(existing=existing, live=live, new_facts=new_facts),
                tools=[func],
                tool_call_limit=1,
            )
            return captured
        except Exception as e:
            log_warning(f"EntityMemoryStore: supersession judgment failed, keeping all facts: {e}")
            return []

    def _build_supersession_messages(
        self, existing: EntityMemory, live: List[Dict[str, Any]], new_facts: List[str]
    ) -> List[Any]:
        from agno.models.message import Message

        if self.config.system_message:
            system_content = self.config.system_message
        else:
            system_content = _SUPERSESSION_SYSTEM_PROMPT
            if self.config.instructions:
                system_content += f"\n## Additional Instructions\n\n{self.config.instructions}\n"
            if self.config.additional_instructions:
                system_content += f"\n{self.config.additional_instructions}\n"

        label = f"{existing.entity_type}/{existing.entity_id}"
        live_lines = []
        for f in live:
            as_of = str(f.get("updated_at") or f.get("created_at") or "")[:10]
            as_of_text = f" (as of {as_of})" if as_of else ""
            live_lines.append(f"- [{f.get('id')}] {f.get('content')}{as_of_text}")
        new_lines = [f"- {f}" for f in new_facts]

        user_content = (
            f"Entity: {label}\n\nLive facts:\n"
            + "\n".join(live_lines)
            + "\n\nNewly stated facts:\n"
            + "\n".join(new_lines)
        )
        return [
            Message(role="system", content=system_content),
            Message(role="user", content=user_content),
        ]

    def _apply_supersessions(
        self, entity_obj: EntityMemory, judgments: List[Tuple[str, float]], new_facts: List[str]
    ) -> int:
        """Retire judged facts at or above the threshold. Returns the count retired.

        Only pre-existing facts can be retired - the judge never saw the ids of
        the facts added by this write, and a hallucinated id must not touch them.
        """
        if not judgments:
            return 0

        new_normalized = {_normalize_fact_text(f) for f in new_facts}
        eligible_ids = {
            f.get("id")
            for f in entity_obj.live_facts()
            if isinstance(f, dict) and _normalize_fact_text(str(f.get("content", ""))) not in new_normalized
        }

        superseded_by = "superseded"
        if len(new_facts) == 1:
            for f in entity_obj.live_facts():
                if isinstance(f, dict) and _normalize_fact_text(str(f.get("content", ""))) == _normalize_fact_text(
                    new_facts[0]
                ):
                    superseded_by = str(f.get("id"))
                    break

        count = 0
        threshold = self.config.supersession_threshold
        for fact_id, confidence in judgments:
            if confidence < threshold:
                continue
            if fact_id not in eligible_ids:
                continue
            if entity_obj.retire_fact(fact_id, superseded_by=superseded_by):
                count += 1
        return count

    def _repair_far_edge_types(
        self,
        entity_obj: EntityMemory,
        user_id: Optional[str],
        agent_id: Optional[str],
        team_id: Optional[str],
        namespace: str,
        max_repairs: int = 10,
    ) -> None:
        """After an unknown -> real type upgrade, fix the reciprocal edges on the
        far ends, which still carry entity_type="unknown" for this entity."""
        for rel in (getattr(entity_obj, "relationships", None) or [])[:max_repairs]:
            if not isinstance(rel, dict):
                continue
            far = self.get(
                entity_id=rel.get("entity_id", ""),
                entity_type=rel.get("entity_type", ""),
                user_id=user_id,
                namespace=namespace,
            )
            if far is None:
                continue
            changed = False
            for far_rel in getattr(far, "relationships", None) or []:
                if (
                    isinstance(far_rel, dict)
                    and far_rel.get("entity_id") == entity_obj.entity_id
                    and far_rel.get("entity_type") != entity_obj.entity_type
                ):
                    far_rel["entity_type"] = entity_obj.entity_type
                    changed = True
            if changed:
                self._save_entity(entity=far, user_id=user_id, agent_id=agent_id, team_id=team_id, namespace=namespace)

    async def _arepair_far_edge_types(
        self,
        entity_obj: EntityMemory,
        user_id: Optional[str],
        agent_id: Optional[str],
        team_id: Optional[str],
        namespace: str,
        max_repairs: int = 10,
    ) -> None:
        """Async version of _repair_far_edge_types."""
        for rel in (getattr(entity_obj, "relationships", None) or [])[:max_repairs]:
            if not isinstance(rel, dict):
                continue
            far = await self.aget(
                entity_id=rel.get("entity_id", ""),
                entity_type=rel.get("entity_type", ""),
                user_id=user_id,
                namespace=namespace,
            )
            if far is None:
                continue
            changed = False
            for far_rel in getattr(far, "relationships", None) or []:
                if (
                    isinstance(far_rel, dict)
                    and far_rel.get("entity_id") == entity_obj.entity_id
                    and far_rel.get("entity_type") != entity_obj.entity_type
                ):
                    far_rel["entity_type"] = entity_obj.entity_type
                    changed = True
            if changed:
                await self._asave_entity(
                    entity=far, user_id=user_id, agent_id=agent_id, team_id=team_id, namespace=namespace
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
        aliases: Optional[List[str]] = None,
    ) -> Tuple[EntityMemory, bool, bool, Optional[str]]:
        """Create or merge the entity in memory.

        Returns (entity, created, revived, stale_row_key). stale_row_key is set
        when the merge changed the entity's type (a minimal 'unknown' entity
        acquiring its real type), so the caller must delete the old row after
        saving the new one.
        """
        now = _utc_now_iso()
        created = False
        revived = False
        stale_row_key: Optional[str] = None
        normalized_type = _normalize_entity_type(entity_type) or _UNKNOWN_ENTITY_TYPE

        if existing is None:
            created = True
            entity_obj = self.schema(
                entity_id=_slugify(entity),
                entity_type=normalized_type,
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

            # A minimal entity created by link_entities acquires its real type;
            # the row key embeds the type, so the old row must be replaced.
            if entity_obj.entity_type == _UNKNOWN_ENTITY_TYPE and normalized_type != _UNKNOWN_ENTITY_TYPE:
                stale_row_key = self._build_entity_db_id(entity_obj.entity_id, entity_obj.entity_type, namespace)
                entity_obj.entity_type = normalized_type

            # Remember the name variant this write arrived under, bounded so the
            # list cannot grow without limit. A name that differs from every one
            # on file is kept even when it slugs to this same row: that is how a
            # punctuation-only merge ("Acme, Inc." onto "Acme Inc") stays
            # visible and searchable instead of being written nowhere.
            incoming_name = entity.strip()
            existing_aliases = list(getattr(entity_obj, "aliases", None) or [])
            known_names = [entity_obj.name or ""] + existing_aliases
            if (
                incoming_name
                and len(existing_aliases) < 8
                and all(_normalize_name(incoming_name) != _normalize_name(n) for n in known_names if n)
            ):
                entity_obj.aliases = [*existing_aliases, incoming_name]

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

        # Explicit aliases (the write path for the resolution ladder's third
        # rung): merged with dedupe against the name and existing aliases,
        # bounded at 8.
        for alias in aliases or []:
            alias = alias.strip()
            existing_aliases = list(getattr(entity_obj, "aliases", None) or [])
            known = [entity_obj.name or ""] + existing_aliases
            if (
                alias
                and len(existing_aliases) < 8
                and all(_normalize_name(alias) != _normalize_name(n) for n in known if n)
            ):
                entity_obj.aliases = [*existing_aliases, alias]

        entity_obj.updated_at = now
        return entity_obj, created, revived, stale_row_key

    def _remember_message(
        self,
        entity_obj: EntityMemory,
        created: bool,
        revived: bool,
        facts: List[str],
        events: List[str],
        note: Optional[str],
        superseded_count: int = 0,
        duplicate_count: int = 0,
        siblings: Optional[List[str]] = None,
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
        superseded_text = f" Superseded {superseded_count} earlier fact(s)." if superseded_count else ""
        duplicate_text = f" Skipped {duplicate_count} already-recorded fact(s)." if duplicate_count else ""
        revived_text = " The entity was archived and is now revived." if revived else ""
        # Types are never merged across, so a same-name sibling is a separate
        # record the model may not have meant to create. Say so while it can
        # still restate under the right type.
        sibling_text = ""
        if siblings:
            sibling_text = (
                f" Note: {', '.join(siblings)} already exists under this name - if you meant that one,"
                " restate with its type."
            )
        return f"{verb} {label}.{recorded}{superseded_text}{duplicate_text}{revived_text}{sibling_text}"

    def _same_name_siblings(self, entity_obj: EntityMemory, rows: List[Dict[str, Any]]) -> List[str]:
        """Labels of rows sharing this entity's id under a different type."""
        labels = []
        for row in rows:
            row_type = row.get("entity_type")
            if row_type and row_type != entity_obj.entity_type:
                labels.append(f"{row_type}/{entity_obj.entity_id}")
        return labels

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

        for endpoint in (entity, related_entity):
            ambiguous = self._ambiguous_name(entity=endpoint, user_id=user_id, namespace=effective_namespace)
            if ambiguous:
                return ambiguous
        entity, entity_qualifier = self._qualified(entity=entity, user_id=user_id, namespace=effective_namespace)
        related_entity, related_qualifier = self._qualified(
            entity=related_entity, user_id=user_id, namespace=effective_namespace
        )

        source = self._resolve_or_create_minimal(
            entity,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            namespace=effective_namespace,
            entity_type=entity_qualifier,
        )
        target = self._resolve_or_create_minimal(
            related_entity,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            namespace=effective_namespace,
            entity_type=related_qualifier,
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

        for endpoint in (entity, related_entity):
            ambiguous = await self._aambiguous_name(entity=endpoint, user_id=user_id, namespace=effective_namespace)
            if ambiguous:
                return ambiguous
        entity, entity_qualifier = await self._aqualified(entity=entity, user_id=user_id, namespace=effective_namespace)
        related_entity, related_qualifier = await self._aqualified(
            entity=related_entity, user_id=user_id, namespace=effective_namespace
        )

        async with self._write_lock():
            # Both ends are read-modify-written; see aremember_about.
            source = await self._aresolve_or_create_minimal(
                entity,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=effective_namespace,
                entity_type=entity_qualifier,
            )
            target = await self._aresolve_or_create_minimal(
                related_entity,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=effective_namespace,
                entity_type=related_qualifier,
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

        query = _blank_to_none(query)
        entity_type = _blank_to_none(entity_type)

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

        query = _blank_to_none(query)
        entity_type = _blank_to_none(entity_type)

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
            shown = live[-max_facts:] if max_facts > 0 else []
            marker = f" (newest {len(shown)} of {len(live)} facts)" if len(live) > len(shown) else ""
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
        ambiguous = self._ambiguous_name(entity=entity, user_id=user_id, namespace=effective_namespace)
        if ambiguous:
            return ambiguous
        entity, qualifier = self._qualified(entity=entity, user_id=user_id, namespace=effective_namespace)
        entity_obj = self._resolve(entity=entity, entity_type=qualifier, user_id=user_id, namespace=effective_namespace)
        if entity_obj is None:
            return f"No entity found matching {entity!r}."

        result, should_save, detached = self._apply_forget(entity_obj=entity_obj, fact=fact)
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
            if detached is not None:
                self._detach_far_edge(entity_obj=entity_obj, edge=detached)
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
        async with self._write_lock():
            # Read-modify-write; see aremember_about.
            ambiguous = await self._aambiguous_name(entity=entity, user_id=user_id, namespace=effective_namespace)
            if ambiguous:
                return ambiguous
            entity, qualifier = await self._aqualified(entity=entity, user_id=user_id, namespace=effective_namespace)
            entity_obj = await self._aresolve(
                entity=entity, entity_type=qualifier, user_id=user_id, namespace=effective_namespace
            )
            if entity_obj is None:
                return f"No entity found matching {entity!r}."

            result, should_save, detached = self._apply_forget(entity_obj=entity_obj, fact=fact)
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
                if detached is not None:
                    await self._adetach_far_edge(entity_obj=entity_obj, edge=detached)
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

    def _apply_forget(
        self, entity_obj: EntityMemory, fact: Optional[str]
    ) -> Tuple[str, bool, Optional[Dict[str, Any]]]:
        """Apply forget in memory.

        Returns (message, should_save, detached_edge). The far end of a removed
        edge is written by the caller, which knows whether its db is async.
        """
        label = f"{entity_obj.entity_type}/{entity_obj.entity_id}"

        # No fact: archive the entity.
        if fact is None or not fact.strip():
            if getattr(entity_obj, "archived_at", None):
                return f"{label} is already archived.", False, None
            entity_obj.archived_at = _utc_now_iso()
            entity_obj.updated_at = _utc_now_iso()
            return (
                f"Archived {label}. It will no longer be recalled; search_entities can still "
                f"find it, and any new remember_about about it revives it.",
                True,
                None,
            )

        # Fact given: match against live fact content.
        needle = _normalize_fact_text(fact)
        live = entity_obj.live_facts()

        exact = [f for f in live if isinstance(f, dict) and _normalize_fact_text(str(f.get("content", ""))) == needle]
        if exact:
            for f in exact:
                self._retire(entity_obj, f)
            entity_obj.updated_at = _utc_now_iso()
            return f"Retired fact on {label}: {exact[0].get('content')}", True, None

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
            return f"Retired fact on {label}: {contains[0].get('content')}", True, None
        if len(contains) > 1:
            listing = "\n".join(f"  - {f.get('content')}" for f in contains)
            return (
                f"Multiple facts on {label} match {fact!r}; nothing was retired. "
                f"Call forget again with the exact wording of one of:\n{listing}",
                False,
                None,
            )

        # No fact matched: try the relationships. A correction that changes a
        # relation ("written_in Rust" -> Go) has no other retirement path, and
        # a stale edge renders forever, undated, next to the corrected one.
        edge_message, edge_removed, detached = self._forget_edge(entity_obj=entity_obj, needle=needle, label=label)
        if edge_message is not None:
            return edge_message, edge_removed, detached

        # Then the events. The instructions route positions and opinions here,
        # so a retraction ("that rumour was wrong") lands on the one store
        # nothing could correct: the judge only ever sees live facts, and a
        # contradicting event just appended beside the retracted one.
        event_message, event_removed = self._forget_event(entity_obj=entity_obj, needle=needle, label=label)
        if event_message is not None:
            return event_message, event_removed, None

        if not live:
            return f"No matching fact on {label}. It has no live facts.", False, None
        bounded = live[:10]
        listing = "\n".join(f"  - {f.get('content') if isinstance(f, dict) else f}" for f in bounded)
        more = f"\n  ... and {len(live) - len(bounded)} more" if len(live) > len(bounded) else ""
        return f"No matching fact on {label}. Its live facts are:\n{listing}{more}", False, None

    def _name_rows(self, entity: str, user_id: Optional[str], namespace: str) -> List[Dict[str, Any]]:
        """Every stored row this bare name could mean.

        Rows keyed by the slug, plus the exact-name and alias candidates
        ``_resolve`` would reach - a row whose id was set by an external writer
        ("harbor_co_001") is invisible to a slug-only lookup, so it used to
        evade the ambiguity guard and be unreachable through the qualified form.
        """
        name = _normalize_name(entity)
        rows = list(self._get_rows_by_entity_id(entity_id=_slugify(entity), user_id=user_id, namespace=namespace))
        seen = {row.get("learning_id") for row in rows}
        for row in self._name_candidates(entity=entity, user_id=user_id, namespace=namespace):
            if row.get("learning_id") in seen:
                continue
            parsed = self.schema.from_dict(row.get("content"))
            if parsed is None:
                continue
            names = [getattr(parsed, "name", None) or ""] + list(getattr(parsed, "aliases", None) or [])
            if any(candidate and _normalize_name(str(candidate)) == name for candidate in names):
                rows.append(row)
                seen.add(row.get("learning_id"))
        return rows

    async def _aname_rows(self, entity: str, user_id: Optional[str], namespace: str) -> List[Dict[str, Any]]:
        """Async version of _name_rows."""
        name = _normalize_name(entity)
        rows = list(
            await self._aget_rows_by_entity_id(entity_id=_slugify(entity), user_id=user_id, namespace=namespace)
        )
        seen = {row.get("learning_id") for row in rows}
        for row in await self._aname_candidates(entity=entity, user_id=user_id, namespace=namespace):
            if row.get("learning_id") in seen:
                continue
            parsed = self.schema.from_dict(row.get("content"))
            if parsed is None:
                continue
            names = [getattr(parsed, "name", None) or ""] + list(getattr(parsed, "aliases", None) or [])
            if any(candidate and _normalize_name(str(candidate)) == name for candidate in names):
                rows.append(row)
                seen.add(row.get("learning_id"))
        return rows

    @staticmethod
    def _ambiguity_message(entity: str, rows: List[Dict[str, Any]]) -> Optional[str]:
        """A refusal listing every type this name resolves to, or None."""
        types = sorted({str(row.get("entity_type")) for row in rows if row.get("entity_type")})
        if len(types) < 2:
            return None
        listing = "\n".join(f"  - {t}/{entity}" for t in types)
        return f"{entity!r} matches more than one entity; nothing was changed. Call again naming one of:\n{listing}"

    def _ambiguous_name(self, entity: str, user_id: Optional[str], namespace: str) -> Optional[str]:
        """link_entities and forget carry no entity_type, and types are never
        merged across, so a bare "Harbor" would silently pick whichever row
        sorted first and leave the other permanently unaddressable."""
        name, qualifier = self._qualified(entity=entity, user_id=user_id, namespace=namespace)
        if qualifier:
            return None
        return self._ambiguity_message(name, self._name_rows(entity=name, user_id=user_id, namespace=namespace))

    async def _aambiguous_name(self, entity: str, user_id: Optional[str], namespace: str) -> Optional[str]:
        """Async version of _ambiguous_name."""
        name, qualifier = await self._aqualified(entity=entity, user_id=user_id, namespace=namespace)
        if qualifier:
            return None
        return self._ambiguity_message(name, await self._aname_rows(entity=name, user_id=user_id, namespace=namespace))

    def _qualified(
        self, entity: str, user_id: Optional[str], namespace: str, declared_type: Optional[str] = None
    ) -> Tuple[str, Optional[str]]:
        """Read back the "type/name" form the ambiguity reply asks for.

        A prefix only counts when it names one of the types actually stored
        under the remainder, so an entity called "AC/DC" stays one name.

        remember_about is the one tool that declares its own entity_type, and
        it passes it here: the first write under a qualified name has no row to
        recognise the prefix from, so the whole string was slugged into a
        phantom (project/Harbor -> project/project_harbor) that no later call
        could reach.
        """
        remainder = entity.partition("/")[2]
        if not remainder:
            return entity, None
        rows = self._name_rows(entity=remainder, user_id=user_id, namespace=namespace)
        known = [str(r.get("entity_type")) for r in rows if r.get("entity_type")]
        if declared_type:
            known.append(declared_type)
        return _split_qualified_name(entity, known)

    async def _aqualified(
        self, entity: str, user_id: Optional[str], namespace: str, declared_type: Optional[str] = None
    ) -> Tuple[str, Optional[str]]:
        """Async version of _qualified."""
        remainder = entity.partition("/")[2]
        if not remainder:
            return entity, None
        rows = await self._aname_rows(entity=remainder, user_id=user_id, namespace=namespace)
        known = [str(r.get("entity_type")) for r in rows if r.get("entity_type")]
        if declared_type:
            known.append(declared_type)
        return _split_qualified_name(entity, known)

    def _forget_event(self, entity_obj: EntityMemory, needle: str, label: str) -> Tuple[Optional[str], bool]:
        """Retire an event the caller named, matched like a fact.

        Returns (None, False) when nothing matches, so the caller falls through
        to its no-match reply.
        """
        events = [e for e in (getattr(entity_obj, "events", None) or []) if isinstance(e, dict)]
        exact = [e for e in events if _normalize_fact_text(str(e.get("content", ""))) == needle]
        matches = exact or [
            e
            for e in events
            if needle in _normalize_fact_text(str(e.get("content", "")))
            or _normalize_fact_text(str(e.get("content", ""))) in needle
        ]
        if not matches:
            return None, False
        # Several DIFFERENT events matching loosely is ambiguous; several exact
        # copies of the same one is not - retire the set, or the reply says
        # "Retired" while the event keeps rendering.
        if len(matches) > 1 and not exact:
            listing = "\n".join(f"  - {e.get('content')}" for e in matches)
            return (
                f"Multiple events on {label} match {needle!r}; nothing was retired. "
                f"Call forget again with the exact wording of one of:\n{listing}",
                False,
            )

        retired = matches[0]
        entity_obj.events = [e for e in events if e not in matches]
        entity_obj.updated_at = _utc_now_iso()
        return f"Retired event on {label}: {retired.get('content')}", True

    def _forget_edge(
        self, entity_obj: EntityMemory, needle: str, label: str
    ) -> Tuple[Optional[str], bool, Optional[Dict[str, Any]]]:
        """Retire a relationship whose text the caller named.

        Matched the way the model sees an edge rendered - "written_in -> Rust",
        or either half alone. Returns (None, False) when nothing matches, so
        the caller can fall through to its no-match reply.
        """
        edges = [r for r in (getattr(entity_obj, "relationships", None) or []) if isinstance(r, dict)]
        matches = []
        qualified_matches = []
        directed_matches = []
        for edge in edges:
            relation = _normalize_fact_text(str(edge.get("relation", "")))
            # The context block renders the far end's DISPLAY name ("Sarah
            # Chen") while the edge stores its slug, so match both - the
            # docstring tells the model to name the edge as it is rendered,
            # and every multi-word far end failed that instruction.
            slug = _normalize_fact_text(str(edge.get("entity_id", "")))
            spaced = _normalize_fact_text(str(edge.get("entity_id", "")).replace("_", " "))
            plain = {t for t in (slug, spaced) if t}
            # The far end can also be named in the qualified "project/Harbor"
            # form the other tools teach, which is the only way to tell two
            # same-slug far ends apart.
            far_type = _normalize_fact_text(str(edge.get("entity_type", "")))
            qualified = {f"{far_type}/{t}" for t in plain} if far_type else set()
            targets = plain | qualified
            arrow = "<-" if edge.get("direction") == "incoming" else "->"
            rendered = {_normalize_fact_text(f"{edge.get('relation', '')} {target}") for target in targets}
            rendered |= {_normalize_fact_text(f"{edge.get('relation', '')} {arrow} {target}") for target in targets}
            names_far_end = any(_mentions(needle, t) for t in targets) or _slug_phrase_in(needle, slug)
            if needle in ({relation} | targets | rendered) or (
                relation and _mentions(needle, relation) and names_far_end
            ):
                matches.append(edge)
                if any(_mentions(needle, t) for t in qualified):
                    qualified_matches.append(edge)
                if arrow in needle:
                    directed_matches.append(edge)
        if not matches:
            return None, False, None
        # A needle naming the far end's type picks that edge out of its
        # same-slug siblings; "works_on -> harbor" still matches both.
        if qualified_matches:
            matches = qualified_matches
        # Same for the arrow: a relation asserted from both sides leaves two
        # edges that differ only in direction, and the block renders them as
        # "rel -> far" and "rel <- far". Naming one retires that one.
        if directed_matches and len(directed_matches) < len(matches):
            matches = [edge for edge in matches if edge in directed_matches]
        # Edges written before add_relationship became idempotent can be exact
        # duplicates: the listing below would offer two identical candidates
        # that no wording can tell apart, so retire the whole set instead.
        # entity_type is part of the identity here for the same reason it is in
        # add_relationship - project/Harbor and company/Harbor are two links,
        # and retiring both while detaching one reciprocal leaves the graph
        # one-sided.
        identical = {(e.get("relation"), e.get("entity_id"), e.get("entity_type"), e.get("direction")) for e in matches}
        if len(matches) > 1 and len(identical) > 1:
            # Rendered the way the block renders them, direction included: two
            # candidates printed identically ask the model to pick between the
            # same string twice, and it never can.
            listing = "\n".join(
                f"  - {e.get('relation')} {'<-' if e.get('direction') == 'incoming' else '->'} "
                f"{e.get('entity_type')}/{e.get('entity_id')}"
                for e in matches
            )
            return (
                f"Multiple relationships on {label} match; nothing was removed. "
                f"Call forget again naming one of:\n{listing}",
                False,
                None,
            )

        edge = matches[0]
        entity_obj.relationships = [r for r in edges if r not in matches]
        entity_obj.updated_at = _utc_now_iso()
        arrow = "<-" if edge.get("direction") == "incoming" else "->"
        return (
            f"Removed relationship on {label}: {edge.get('relation')} {arrow} "
            f"{edge.get('entity_type')}/{edge.get('entity_id')}",
            True,
            edge,
        )

    @staticmethod
    def _without_reciprocal(far: EntityMemory, entity_obj: EntityMemory, edge: Dict[str, Any]) -> Optional[List[Any]]:
        """The far end's edges minus the one pointing back, or None if absent."""
        kept = [
            r
            for r in (getattr(far, "relationships", None) or [])
            if not (
                isinstance(r, dict)
                and r.get("entity_id") == entity_obj.entity_id
                and r.get("relation") == edge.get("relation")
                # Type too: project/Harbor and company/Harbor share a slug, and
                # retiring one edge must not strip the other's reciprocal.
                and r.get("entity_type") == entity_obj.entity_type
            )
        ]
        if len(kept) == len(getattr(far, "relationships", None) or []):
            return None
        return kept

    def _detach_far_edge(self, entity_obj: EntityMemory, edge: Dict[str, Any]) -> None:
        """Drop the reciprocal edge, so the graph does not go one-sided.

        Best effort: a far end that cannot be loaded or saved leaves a dangling
        incoming edge, which renders as a name and misleads nobody.
        """
        namespace = entity_obj.namespace or self.config.namespace
        far = self.get(
            entity_id=str(edge.get("entity_id", "")),
            entity_type=str(edge.get("entity_type", "")),
            user_id=entity_obj.user_id,
            namespace=namespace,
        )
        if far is None:
            return
        kept = self._without_reciprocal(far=far, entity_obj=entity_obj, edge=edge)
        if kept is None:
            return
        far.relationships = kept
        far.updated_at = _utc_now_iso()
        self._save_entity(
            entity=far,
            user_id=entity_obj.user_id,
            agent_id=entity_obj.agent_id,
            team_id=entity_obj.team_id,
            namespace=namespace,
        )

    async def _adetach_far_edge(self, entity_obj: EntityMemory, edge: Dict[str, Any]) -> None:
        """Async version of _detach_far_edge.

        The sync helpers no-op against an AsyncBaseDb, which left the far end
        holding an edge the near end had already dropped.
        """
        namespace = entity_obj.namespace or self.config.namespace
        far = await self.aget(
            entity_id=str(edge.get("entity_id", "")),
            entity_type=str(edge.get("entity_type", "")),
            user_id=entity_obj.user_id,
            namespace=namespace,
        )
        if far is None:
            return
        kept = self._without_reciprocal(far=far, entity_obj=entity_obj, edge=edge)
        if kept is None:
            return
        far.relationships = kept
        far.updated_at = _utc_now_iso()
        await self._asave_entity(
            entity=far,
            user_id=entity_obj.user_id,
            agent_id=entity_obj.agent_id,
            team_id=entity_obj.team_id,
            namespace=namespace,
        )

    def _resolve(
        self,
        entity: str,
        entity_type: Optional[str],
        user_id: Optional[str],
        namespace: str,
    ) -> Optional[EntityMemory]:
        """Resolve an entity by name within the namespace.

        Deterministic, no LLM: normalized id (exact type first, then across
        types), then exact name, then aliases. Matching is deliberately narrow -
        a wrong merge has no unmerge.
        """
        slug = _slugify(entity)
        normalized_type = _normalize_entity_type(entity_type)

        if normalized_type:
            found = self.get(entity_id=slug, entity_type=normalized_type, user_id=user_id, namespace=namespace)
            if found is not None:
                return found

        rows = self._get_rows_by_entity_id(entity_id=slug, user_id=user_id, namespace=namespace)
        for row in rows:
            parsed = self.schema.from_dict(row.get("content"))
            if parsed is not None and _types_can_merge(normalized_type, getattr(parsed, "entity_type", None)):
                return parsed

        candidates = self._name_candidates(entity=entity, user_id=user_id, namespace=namespace)
        return self._match_name_or_alias(candidates=candidates, entity=entity, entity_type=normalized_type)

    async def _aresolve(
        self,
        entity: str,
        entity_type: Optional[str],
        user_id: Optional[str],
        namespace: str,
    ) -> Optional[EntityMemory]:
        """Async version of _resolve."""
        slug = _slugify(entity)
        normalized_type = _normalize_entity_type(entity_type)

        if normalized_type:
            found = await self.aget(entity_id=slug, entity_type=normalized_type, user_id=user_id, namespace=namespace)
            if found is not None:
                return found

        rows = await self._aget_rows_by_entity_id(entity_id=slug, user_id=user_id, namespace=namespace)
        for row in rows:
            parsed = self.schema.from_dict(row.get("content"))
            if parsed is not None and _types_can_merge(normalized_type, getattr(parsed, "entity_type", None)):
                return parsed

        candidates = await self._aname_candidates(entity=entity, user_id=user_id, namespace=namespace)
        return self._match_name_or_alias(candidates=candidates, entity=entity, entity_type=normalized_type)

    def _write_lock(self) -> Any:
        """The write lock for the running event loop.

        Keyed by the loop itself, weakly: a store outlives the loops that use
        it (a worker that restarts its loop, a test suite that runs many), and
        an id-keyed cache would both grow forever and hand a new loop the lock
        of a dead one that happened to reuse its address - which hangs if that
        lock died held.
        """
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No loop to key on (and nothing to serialize against either):
            # a fresh lock is uncontended and correct. None cannot be a
            # WeakKeyDictionary key.
            return asyncio.Lock()
        lock = self._async_write_locks.get(loop)
        if lock is None:
            lock = asyncio.Lock()
            self._async_write_locks[loop] = lock
        return lock

    def _name_candidates(self, entity: str, user_id: Optional[str], namespace: str) -> List[Dict[str, Any]]:
        """Fetch candidate rows for name/alias matching via the text query surface.

        The probes are anchored to the JSON shape of a stored name ('name": "..')
        and to the quoted value (for aliases), so unrelated rows whose FACTS
        mention the name cannot crowd the true row out of the window.

        Database errors RAISE: a resolution miss caused by a failing backend
        would silently create a duplicate entity instead of merging.
        """
        db = self._sync_db()
        if db is None:
            return []
        if not callable(getattr(db, "search_learnings", None)):
            # Resolution, not just search: without the query surface an alias
            # or an externally-keyed row stops resolving past this window and
            # the write mints a duplicate. Say so where it happens.
            self._log_degraded_search_once()
            return self._get_recent_rows(user_id=user_id, namespace=namespace, limit=50)
        try:
            rows: List[Dict[str, Any]] = []
            seen_ids: set = set()
            for probe in self._name_probes(entity):
                for row in (
                    db.search_learnings(
                        query=probe,
                        learning_type=self.learning_type,
                        namespace=namespace,
                        user_id=user_id if namespace == "user" else None,
                        limit=20,
                    )
                    or []
                ):
                    row_id = row.get("learning_id")
                    if row_id not in seen_ids:
                        seen_ids.add(row_id)
                        rows.append(row)
            return rows
        except NotImplementedError:
            self._log_degraded_search_once()
            return self._get_recent_rows(user_id=user_id, namespace=namespace, limit=50)

    async def _aname_candidates(self, entity: str, user_id: Optional[str], namespace: str) -> List[Dict[str, Any]]:
        """Async version of _name_candidates."""
        if not self.db:
            return []
        if not callable(getattr(self.db, "search_learnings", None)):
            # See the sync twin.
            self._log_degraded_search_once()
            return await self._aget_recent_rows(user_id=user_id, namespace=namespace, limit=50)
        try:
            rows: List[Dict[str, Any]] = []
            seen_ids: set = set()
            for probe in self._name_probes(entity):
                if isinstance(self.db, AsyncBaseDb):
                    probe_rows = await self.db.search_learnings(
                        query=probe,
                        learning_type=self.learning_type,
                        namespace=namespace,
                        user_id=user_id if namespace == "user" else None,
                        limit=20,
                    )
                else:
                    probe_rows = self.db.search_learnings(
                        query=probe,
                        learning_type=self.learning_type,
                        namespace=namespace,
                        user_id=user_id if namespace == "user" else None,
                        limit=20,
                    )
                for row in probe_rows or []:
                    row_id = row.get("learning_id")
                    if row_id not in seen_ids:
                        seen_ids.add(row_id)
                        rows.append(row)
            return rows
        except NotImplementedError:
            self._log_degraded_search_once()
            return await self._aget_recent_rows(user_id=user_id, namespace=namespace, limit=50)

    @staticmethod
    def _name_probes(entity: str) -> List[str]:
        """Anchored search probes for a display name: the JSON name-field shape
        and the quoted value (which also matches an alias entry)."""
        stripped = entity.strip()
        return [f'name": "{stripped}', f'"{stripped}"']

    def _get_recent_rows(self, user_id: Optional[str], namespace: str, limit: int) -> List[Dict[str, Any]]:
        db = self._sync_db()
        if db is None:
            return []
        try:
            rows = db.get_learnings(
                learning_type=self.learning_type,
                namespace=namespace,
                user_id=user_id if namespace == "user" else None,
                limit=limit,
            )
            return rows or []
        except Exception as e:
            log_debug(f"EntityMemoryStore._get_recent_rows failed: {e}")
            return []

    async def _aget_recent_rows(self, user_id: Optional[str], namespace: str, limit: int) -> List[Dict[str, Any]]:
        try:
            if isinstance(self.db, AsyncBaseDb):
                rows = await self.db.get_learnings(
                    learning_type=self.learning_type,
                    namespace=namespace,
                    user_id=user_id if namespace == "user" else None,
                    limit=limit,
                )
            else:
                rows = self.db.get_learnings(  # type: ignore[union-attr]
                    learning_type=self.learning_type,
                    namespace=namespace,
                    user_id=user_id if namespace == "user" else None,
                    limit=limit,
                )
            return rows or []
        except Exception as e:
            log_debug(f"EntityMemoryStore._aget_recent_rows failed: {e}")
            return []

    def _match_name_or_alias(
        self, candidates: List[Dict[str, Any]], entity: str, entity_type: Optional[str] = None
    ) -> Optional[EntityMemory]:
        """Exact (normalized) name match first, then exact alias match.

        A candidate of a different canonical type is a name collision, not the
        same entity, and is skipped - see ``_types_can_merge``.
        """
        target = _normalize_name(entity)
        parsed_candidates: List[EntityMemory] = []
        for row in self._order_rows(candidates):
            parsed = self.schema.from_dict(row.get("content"))
            if parsed is not None and _types_can_merge(entity_type, getattr(parsed, "entity_type", None)):
                parsed_candidates.append(parsed)

        for parsed in parsed_candidates:
            name = getattr(parsed, "name", None)
            if name and _normalize_name(name) == target:
                return parsed
        for parsed in parsed_candidates:
            aliases = getattr(parsed, "aliases", None) or []
            if any(_normalize_name(str(alias)) == target for alias in aliases):
                return parsed
        return None

    def _resolve_or_create_minimal(
        self,
        entity: str,
        user_id: Optional[str],
        agent_id: Optional[str],
        team_id: Optional[str],
        namespace: str,
        entity_type: Optional[str] = None,
    ) -> EntityMemory:
        """Resolve an entity by name, creating a minimal 'unknown' entity if absent."""
        found = self._resolve(entity=entity, entity_type=entity_type, user_id=user_id, namespace=namespace)
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
        entity_type: Optional[str] = None,
    ) -> EntityMemory:
        """Async version of _resolve_or_create_minimal."""
        found = await self._aresolve(entity=entity, entity_type=entity_type, user_id=user_id, namespace=namespace)
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
            entity_type=_UNKNOWN_ENTITY_TYPE,
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
        db = self._sync_db()
        if db is None:
            return []
        try:
            rows = db.get_learnings(
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
        db = self._sync_db()
        if db is None:
            return None

        effective_namespace = namespace or self.config.namespace

        try:
            result = db.get_learning(
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
        db = self._sync_db()
        if db is None:
            return []

        effective_namespace = namespace or self.config.namespace
        entity_type = _normalize_entity_type(entity_type)
        if effective_namespace == "user" and not user_id:
            log_warning("EntityMemoryStore.list_entities: namespace='user' requires user_id")
            return []

        try:
            for fetch in self._archive_headroom(limit=limit, include_archived=include_archived):
                results = db.get_learnings(
                    learning_type=self.learning_type,
                    entity_type=entity_type,
                    namespace=effective_namespace,
                    user_id=user_id if effective_namespace == "user" else None,
                    limit=fetch,
                )
                rows = results or []
                entities = self._parse_rows(rows, limit=limit, include_archived=include_archived)
                if len(entities) >= limit or len(rows) < fetch:
                    return entities
            return entities
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
        entity_type = _normalize_entity_type(entity_type)
        if effective_namespace == "user" and not user_id:
            log_warning("EntityMemoryStore.alist_entities: namespace='user' requires user_id")
            return []

        try:
            for fetch in self._archive_headroom(limit=limit, include_archived=include_archived):
                if isinstance(self.db, AsyncBaseDb):
                    results = await self.db.get_learnings(
                        learning_type=self.learning_type,
                        entity_type=entity_type,
                        namespace=effective_namespace,
                        user_id=user_id if effective_namespace == "user" else None,
                        limit=fetch,
                    )
                else:
                    results = self.db.get_learnings(
                        learning_type=self.learning_type,
                        entity_type=entity_type,
                        namespace=effective_namespace,
                        user_id=user_id if effective_namespace == "user" else None,
                        limit=fetch,
                    )
                rows = results or []
                entities = self._parse_rows(rows, limit=limit, include_archived=include_archived)
                if len(entities) >= limit or len(rows) < fetch:
                    return entities
            return entities
        except Exception as e:
            log_debug(f"EntityMemoryStore.alist_entities failed: {e}")
            return []

    @staticmethod
    def _archive_headroom(limit: int, include_archived: bool) -> List[int]:
        """Fetch sizes to try when listing entities by recency.

        Archived rows are dropped after the fetch, so a fixed headroom quietly
        shortens the listing once enough of the newest rows are archived - and
        the entity directory then claims to be the full index while live
        entities sit just outside the window. Escalate until the listing is
        full or the table is exhausted.
        """
        if include_archived:
            return [limit]
        return [limit * 2, limit * 8, limit * 32]

    @staticmethod
    def _verified_search_window(limit: int) -> Iterator[int]:
        """Fetch sizes to try when searching, until the backend runs out.

        The db-side LIKE matches the whole serialized row, key names included,
        so ordinary words ("name", "content", "events") match every row: a
        fixed window fills with rows that then fail value-only verification and
        the real match, older, is never fetched. Any finite ladder just moves
        the threshold - at 48x a brain needs 481 key-name matches to hide a
        fact - so this yields until the caller stops, which it does when the
        backend returns a short page.
        """
        fetch = max(limit, 1) * 3
        while True:
            yield fetch
            fetch *= 4

    def _anchored_hit(
        self, query: str, entity_type: Optional[str], rows: List[Dict[str, Any]], include_archived: bool
    ) -> List[EntityMemory]:
        """The entity the query NAMES, ahead of the rows that merely mention it.

        search_learnings orders by recency and has no ranking, so an entity
        whose name appears in five newer entities' facts ("works on Harbor
        ingest") fills the verified window with rows that all legitimately
        match, and its own row - older - is never fetched. Both of recall's
        routes then close at once: the directory caps at 50 as well.
        """
        found: List[EntityMemory] = []
        for row in rows:
            if entity_type and row.get("entity_type") != entity_type:
                continue
            entity = self.schema.from_dict(row.get("content"))
            if entity is None:
                continue
            if not include_archived and getattr(entity, "archived_at", None):
                continue
            found.append(entity)
        return found

    @staticmethod
    def _prepend_anchored(anchored: List[EntityMemory], rest: List[EntityMemory], limit: int) -> List[EntityMemory]:
        merged = list(anchored)
        seen = {(e.entity_id, e.entity_type) for e in merged}
        for entity in rest:
            key = (entity.entity_id, entity.entity_type)
            if key in seen:
                continue
            seen.add(key)
            merged.append(entity)
        return merged[:limit]

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
        db = self._sync_db()
        if db is None:
            return []

        effective_namespace = namespace or self.config.namespace
        entity_type = _normalize_entity_type(entity_type)
        if effective_namespace == "user" and not user_id:
            log_warning("EntityMemoryStore.search: namespace='user' requires user_id")
            return []

        if not callable(getattr(db, "search_learnings", None)):
            self._log_degraded_search_once()
            return self._search_client_side(
                query=query,
                entity_type=entity_type,
                user_id=user_id,
                namespace=effective_namespace,
                limit=limit,
                include_archived=include_archived,
            )

        try:
            entities: List[EntityMemory] = []
            for fetch in self._verified_search_window(limit):
                rows = db.search_learnings(
                    query=query,
                    learning_type=self.learning_type,
                    entity_type=entity_type,
                    namespace=effective_namespace,
                    user_id=user_id if effective_namespace == "user" else None,
                    limit=fetch,
                )
                rows = rows or []
                entities = self._filter_rows_by_query(rows, query=query, limit=limit, include_archived=include_archived)
                if len(entities) >= limit or len(rows) < fetch:
                    break
        except NotImplementedError:
            self._log_degraded_search_once()
            return self._search_client_side(
                query=query,
                entity_type=entity_type,
                user_id=user_id,
                namespace=effective_namespace,
                limit=limit,
                include_archived=include_archived,
            )

        anchored = self._anchored_hit(
            query=query,
            entity_type=entity_type,
            rows=self._get_rows_by_entity_id(entity_id=_slugify(query), user_id=user_id, namespace=effective_namespace),
            include_archived=include_archived,
        )
        entities = self._prepend_anchored(anchored, entities, limit)
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
        entity_type = _normalize_entity_type(entity_type)
        if effective_namespace == "user" and not user_id:
            log_warning("EntityMemoryStore.asearch: namespace='user' requires user_id")
            return []

        if not callable(getattr(self.db, "search_learnings", None)):
            self._log_degraded_search_once()
            return await self._asearch_client_side(
                query=query,
                entity_type=entity_type,
                user_id=user_id,
                namespace=effective_namespace,
                limit=limit,
                include_archived=include_archived,
            )

        try:
            entities: List[EntityMemory] = []
            for fetch in self._verified_search_window(limit):
                if isinstance(self.db, AsyncBaseDb):
                    rows = await self.db.search_learnings(
                        query=query,
                        learning_type=self.learning_type,
                        entity_type=entity_type,
                        namespace=effective_namespace,
                        user_id=user_id if effective_namespace == "user" else None,
                        limit=fetch,
                    )
                else:
                    rows = self.db.search_learnings(
                        query=query,
                        learning_type=self.learning_type,
                        entity_type=entity_type,
                        namespace=effective_namespace,
                        user_id=user_id if effective_namespace == "user" else None,
                        limit=fetch,
                    )
                rows = rows or []
                entities = self._filter_rows_by_query(rows, query=query, limit=limit, include_archived=include_archived)
                if len(entities) >= limit or len(rows) < fetch:
                    break
        except NotImplementedError:
            self._log_degraded_search_once()
            return await self._asearch_client_side(
                query=query,
                entity_type=entity_type,
                user_id=user_id,
                namespace=effective_namespace,
                limit=limit,
                include_archived=include_archived,
            )

        anchored = self._anchored_hit(
            query=query,
            entity_type=entity_type,
            rows=await self._aget_rows_by_entity_id(
                entity_id=_slugify(query), user_id=user_id, namespace=effective_namespace
            ),
            include_archived=include_archived,
        )
        entities = self._prepend_anchored(anchored, entities, limit)
        log_debug(f"EntityMemoryStore.asearch: found {len(entities)} entities for query: {query[:50]}")
        return entities

    def _sync_db(self) -> Optional[Any]:
        """The db for sync methods, or None when it is async (logged once).

        A sync call on an AsyncBaseDb would return an un-awaited coroutine and
        surface as a confusing TypeError downstream; refuse it explicitly.
        """
        if self.db is None:
            return None
        if isinstance(self.db, AsyncBaseDb):
            if not self._async_db_in_sync_logged:
                self._async_db_in_sync_logged = True
                log_warning(
                    "EntityMemoryStore: a sync method was called with an async db (AsyncBaseDb). "
                    "Use the async API (arecall/aremember_about/asearch/...) with this backend."
                )
            return None
        return self.db

    def _log_degraded_search_once(self) -> None:
        if not self._degraded_search_logged:
            self._degraded_search_logged = True
            log_warning(
                "EntityMemoryStore: this db backend has no search_learnings implementation. "
                "Entity search and resolution fall back to a scan of the most recently "
                "updated rows, so past roughly 50 entities an alias or an externally-keyed "
                "row stops resolving and a SECOND entity is created for the same thing - "
                "there is no unmerge. Search quality degrades from the same point. "
                "SqliteDb, PostgresDb and AsyncPostgresDb implement the real query surface; "
                "use one of those for a store you intend to grow."
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
        db = self._sync_db()
        if db is None:
            return []
        try:
            results = db.get_learnings(
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
        for row in rows:
            try:
                content = row.get("content", {})
                if not self._matches_query(content=content, query=query):
                    continue
                entity = self.schema.from_dict(content)
                if entity is None:
                    continue
                if not include_archived and getattr(entity, "archived_at", None):
                    continue
                entities.append(entity)
                if len(entities) >= limit:
                    break
            except Exception as e:
                log_debug(f"EntityMemoryStore._filter_rows_by_query: skipping malformed row: {e}")
                continue
        return entities

    def _matches_query(self, content: Dict[str, Any], query: str) -> bool:
        """Check if the entity content's VALUES match the query.

        The db-side ILIKE matches the whole serialized document, keys included;
        this value-scoped check verifies server hits (so "facts" or "name" do
        not match every row) and drives the degraded client-side scan. Both
        sides fold their separators, which is what the server's single-char
        wildcard already does.
        """
        return values_match_query(content, query)

    def delete(
        self,
        entity_id: str,
        entity_type: str,
        namespace: Optional[str] = None,
    ) -> bool:
        """Hard-delete an entity from the store (data API - not exposed as a tool)."""
        db = self._sync_db()
        if db is None:
            return False

        effective_namespace = namespace or self.config.namespace
        try:
            return bool(db.delete_learning(id=self._build_entity_db_id(entity_id, entity_type, effective_namespace)))
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
        db = self._sync_db()
        if db is None:
            return False

        effective_namespace = namespace or self.config.namespace

        try:
            content = entity.to_dict()
            if not content:
                return False

            db.upsert_learning(
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
