"""
Curator
=======
Memory maintenance for LearningMachine.

Keeps memories tidy through:
- Pruning: Remove old memories
- Deduplication: Remove exact/near-exact duplicates

Usage:
    >>> learning = LearningMachine(db=db, model=model, user_profile=True)
    >>>
    >>> # Remove memories older than 90 days, keep max 100
    >>> removed = learning.curator.prune(user_id="alice", max_age_days=90, max_count=100)
    >>>
    >>> # Remove duplicate memories
    >>> deduped = learning.curator.deduplicate(user_id="alice")
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, List

from agno.utils.log import log_debug


@dataclass
class Curator:
    """Memory maintenance. Keeps things tidy.

    Currently supports user_profile store only.
    """

    machine: Any  # LearningMachine

    def prune(
        self,
        user_id: str,
        max_age_days: int = 0,
        max_count: int = 0,
    ) -> int:
        """Remove old memories from user profile.

        Args:
            user_id: User to prune memories for.
            max_age_days: Remove memories older than this (0 = disabled).
            max_count: Keep at most this many memories (0 = disabled).

        Returns:
            Number of memories removed.
        """
        store = self.machine.stores.get("user_profile")
        if not store:
            return 0

        profile = store.get(user_id=user_id)
        if not profile or not hasattr(profile, "memories"):
            return 0

        memories = profile.memories
        if not memories:
            return 0

        original_count = len(memories)

        # Age filter
        if max_age_days > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
            memories = self._filter_by_age(memories=memories, cutoff=cutoff)

        # Count filter (keep newest)
        if max_count > 0 and len(memories) > max_count:
            memories = self._keep_newest(memories=memories, count=max_count)

        removed = original_count - len(memories)

        if removed > 0:
            profile.memories = memories
            store.save(user_id=user_id, profile=profile)
            log_debug(f"Curator.prune: removed {removed} memories for user_id={user_id}")

        return removed

    def deduplicate(
        self,
        user_id: str,
    ) -> int:
        """Remove duplicate memories from user profile.

        Uses exact and near-exact string matching.

        Args:
            user_id: User to deduplicate memories for.

        Returns:
            Number of duplicate memories removed.
        """
        store = self.machine.stores.get("user_profile")
        if not store:
            return 0

        profile = store.get(user_id=user_id)
        if not profile or not hasattr(profile, "memories"):
            return 0

        memories = profile.memories
        if len(memories) < 2:
            return 0

        original_count = len(memories)
        unique_memories = self._remove_duplicates(memories=memories)
        removed = original_count - len(unique_memories)

        if removed > 0:
            profile.memories = unique_memories
            store.save(user_id=user_id, profile=profile)
            log_debug(f"Curator.deduplicate: removed {removed} duplicates for user_id={user_id}")

        return removed

    # =========================================================================
    # Helpers
    # =========================================================================

    def _filter_by_age(
        self,
        memories: List[dict],
        cutoff: datetime,
    ) -> List[dict]:
        """Keep memories newer than cutoff."""
        result = []
        for m in memories:
            created_at = m.get("created_at")
            if not created_at:
                result.append(m)  # Keep if no timestamp
                continue

            try:
                created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                if created >= cutoff:
                    result.append(m)
            except (ValueError, TypeError):
                result.append(m)  # Keep if unparseable

        return result

    def _keep_newest(
        self,
        memories: List[dict],
        count: int,
    ) -> List[dict]:
        """Keep the N newest memories."""
        sorted_memories = sorted(
            memories,
            key=lambda m: m.get("created_at", ""),
            reverse=True,
        )
        return sorted_memories[:count]

    def _remove_duplicates(
        self,
        memories: List[dict],
    ) -> List[dict]:
        """Remove exact and near-exact duplicate memories."""
        seen = set()
        unique = []

        for m in memories:
            content = m.get("content", "")
            normalized = self._normalize(content)

            if normalized not in seen:
                seen.add(normalized)
                unique.append(m)

        return unique

    def _normalize(self, text: str) -> str:
        """Normalize text for comparison."""
        import re

        text = text.lower().strip()
        text = re.sub(r"[^\w\s]", "", text)
        text = re.sub(r"\s+", " ", text)
        return text
