from dataclasses import replace
from datetime import datetime, timezone
from math import exp, log
from typing import Any, List, Optional, Tuple

from pydantic import Field, field_validator

from agno.knowledge.document import Document
from agno.knowledge.reranker.base import Reranker
from agno.knowledge.utils import RECENCY_METADATA_KEY, STORE_RECENCY_METADATA_KEY
from agno.utils.log import log_warning

_SECONDS_PER_DAY = 86400.0
_LN_2 = log(2.0)


def _as_timestamp(value: Any) -> Optional[float]:
    """Read a metadata value as a POSIX timestamp, or None when it is not a time."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        # Milliseconds are common in JSON payloads and are centuries away in seconds.
        return float(value) / 1000.0 if value > 1e11 else float(value)
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return moment.timestamp()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            # fromisoformat accepts a trailing Z only from 3.11.
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).timestamp()
    return None


def _rescaled(scores: List[Optional[float]]) -> List[Optional[float]]:
    """Bring out-of-range scores onto 0-1 without distorting the gaps between them.

    Adapters disagree on scale: pgvector reports 0-1, OpenSearch passes raw BM25 through
    unbounded. Dividing by the largest value is enough to make weight mean the documented
    split. Min-max rescaling would stretch every pool to span the full range, turning a
    narrow relevance gap into a decisive one that recency could never outweigh.
    """
    present = [score for score in scores if score is not None]
    if not present:
        return scores
    highest = max(present)
    lowest = min(present)
    if 0.0 <= lowest and highest <= 1.0:
        # Already on the expected scale: leave the reported values alone.
        return scores
    if highest <= 0.0:
        return [None if score is None else 0.0 for score in scores]
    return [None if score is None else max(score, 0.0) / highest for score in scores]


class RecencyReranker(Reranker):
    """Surfaces recently updated documents without discarding relevance.

    Vector search has no notion of time, so a superseded document ranks as well as the
    revision that replaced it. This blends the search score with an exponential decay on
    a timestamp, so an older document has to be clearly more relevant to outrank a newer
    one. It is a tilt, not a sort by date.

    The timestamp is read from ``Document.meta_data[timestamp_key]``, set when adding
    content as an ISO-8601 string, a datetime, or epoch seconds or milliseconds. Failing
    that, a store's own last-modified time is used: on PgVector, build it with
    ``return_updated_at=True``.

    Documents without a usable timestamp receive no recency term, so they rank purely on
    relevance against the same scale as everything else.
    """

    # A fresh document below the cutoff can only be promoted if it was retrieved.
    candidate_multiplier: int = Field(default=3, ge=1)

    # Metadata key holding the document's own timestamp.
    timestamp_key: str = RECENCY_METADATA_KEY
    # Age at which the recency term has decayed to half.
    half_life_days: float = Field(default=30.0, gt=0.0)
    # 0.0 ranks by relevance alone, 1.0 by age alone.
    weight: float = Field(default=0.3, ge=0.0, le=1.0)
    # Search score keys, in the order they are tried: adapters name this differently.
    score_keys: Tuple[str, ...] = ("similarity_score", "search_score", "score")

    @field_validator("half_life_days", mode="before")
    @classmethod
    def _reject_bool_half_life(cls, value: Any) -> Any:
        # bool is an int subclass, so True would otherwise coerce to 1.0.
        if isinstance(value, bool):
            raise ValueError("half_life_days must be a positive number")
        return value

    @field_validator("weight", mode="before")
    @classmethod
    def _reject_bool_weight(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("weight must be a number between 0.0 and 1.0")
        return value

    def _relevance(self, document: Document) -> Optional[float]:
        """The document's search score, or None when the store did not report one."""
        if document.reranking_score is not None:
            return float(document.reranking_score)
        for key in self.score_keys:
            value = (document.meta_data or {}).get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
        return None

    @staticmethod
    def _relevance_from_rank(position: int) -> float:
        """Stand-in relevance for stores that report no score.

        Most vector dbs return results in relevance order without attaching a number, so
        position carries the ranking even when no score does. Decaying from the top rank
        rather than scaling across the pool keeps a given position worth the same whatever
        the pool width, and never reaches zero, so a fresh tail document can still be
        promoted.
        """
        return 1.0 / (1.0 + position)

    def _recency(self, document: Document, now: float) -> Optional[float]:
        """Decay from 1.0 at ``now`` towards 0.0, halving every ``half_life_days``."""
        meta_data = document.meta_data or {}
        # The user's own document date wins; the store's row timestamp is the fallback.
        timestamp = _as_timestamp(meta_data.get(self.timestamp_key))
        if timestamp is None:
            timestamp = _as_timestamp(meta_data.get(STORE_RECENCY_METADATA_KEY))
        if timestamp is None:
            return None
        age_days = max((now - timestamp) / _SECONDS_PER_DAY, 0.0)
        # ln(2) makes half_life_days a true half-life: the term is 0.5 at that age.
        return exp(-_LN_2 * age_days / self.half_life_days)

    def rerank(self, query: str, documents: List[Document], limit: Optional[int] = None) -> List[Document]:
        if not documents:
            return []

        now = datetime.now(timezone.utc).timestamp()
        # Fall back to rank for the whole pool rather than per document, so scored and
        # unscored documents are never mixed on different scales.
        scores = [self._relevance(document) for document in documents]
        use_rank = all(score is None for score in scores)
        if not use_rank:
            # Adapters report on their own scales: pgvector normalises to 0-1, OpenSearch
            # passes raw BM25 through unbounded. Rescaling the pool keeps weight meaning
            # the documented relevance/recency split whatever the store reported.
            scores = _rescaled(scores)

        dated = 0
        scored: List[Tuple[float, int, Document]] = []
        for position, document in enumerate(documents):
            reported = scores[position]
            if use_rank:
                relevance: float = self._relevance_from_rank(position)
            else:
                relevance = reported if reported is not None else 0.0
            recency = self._recency(document, now)
            if recency is not None:
                dated += 1
            # Relevance is scaled the same way for every document. An undated one simply
            # contributes no recency, rather than keeping an unscaled score that would
            # let it outrank a dated document it is less relevant than.
            score = (1.0 - self.weight) * relevance
            if recency is not None:
                score += self.weight * recency
            scored.append((score, position, document))

        if not dated:
            # Ranking would fall through to relevance alone and look like recency ran.
            log_warning(
                f"RecencyReranker found no usable {self.timestamp_key!r} on any search result, so "
                "ordering is unchanged. Set it in metadata when adding content, or use "
                "PgVector(return_updated_at=True) to rank on the stored last-modified time."
            )

        # The original position breaks ties, so equal scores keep the vector db order.
        scored.sort(key=lambda entry: (-entry[0], entry[1]))

        results: List[Document] = []
        for score, _, document in scored[: limit if limit is not None else len(scored)]:
            # Copy so the caller's documents are not scored in place.
            reranked = replace(document)
            reranked.reranking_score = score
            results.append(reranked)
        return results
