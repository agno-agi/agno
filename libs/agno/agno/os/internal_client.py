"""Shared request builder for internal deliveries to AgentOS run endpoints.

The scheduler and the monitor both fire a component's run endpoint on behalf of
an owner, using the internal service token. Both had their own copy of the
header stamping and the payload scrub, and the copies drifted: the monitor
gained the full ``RESERVED_RUN_METADATA_KEYS`` set while the scheduler still
stripped only the version key, and the two disagreed on whether ``message`` was
a reserved form field. Two copies of a security scrub means the next reserved
key gets fixed once, so it lives here instead.

Only the request is shared. The two response shapes are genuinely different --
a schedule waits for the run to reach a terminal state, a monitor records the
delivery and moves on -- and merging those would help nobody.
"""

import json
from typing import Any, Dict, Iterable, Optional, Tuple
from urllib.parse import quote

from agno.db.schemas.scheduler import RESERVED_RUN_METADATA_KEYS, SCHEDULE_OWNER_HEADER
from agno.utils.log import log_warning


def to_form_value(v: Any) -> str:
    """Convert a payload value to a JSON-safe form string."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (dict, list)):
        return json.dumps(v)
    return str(v)


def build_delivery_headers(
    internal_service_token: str,
    owner_id: Optional[str],
    idempotency_key: Optional[str] = None,
) -> Dict[str, str]:
    """Authorization plus the owner the run should execute as.

    ``idempotency_key`` is forwarded as the header the run routes already read,
    so a delivery sent twice for the same logical event starts one run rather
    than two. It is defence in depth rather than a fix for a reachable bug, and
    it is worth being precise about how much it actually buys:

    - The run routes only honour it when the durable job queue is enabled
      (``QueueConfig(durable=True)``, off by default). The dedup belongs to
      ``enqueue_job`` and is keyed on ``(idempotency_key, user_id)``. Everywhere
      else -- including every deployment on the in-process limiter -- the header
      is accepted and ignored, and a repeated delivery starts a second run.
    - The monitor bumps its event counter *before* delivering, so a worker dying
      mid-delivery does not re-use that sequence number on reclaim. The event is
      lost rather than duplicated, which is why no live duplicate has been
      demonstrated on this path. The key guards the ordering being changed later.
    - It does not deduplicate repeated *content*. A watch restarting a `tail -F`
      re-reads old lines, but they carry new sequence numbers, so they are new
      events by every definition the monitor has. Keying on content instead would
      silently drop a log line that legitimately repeats -- worse than the
      duplicate it would prevent. That one is accepted, not solved.
    """
    headers = {"Authorization": f"Bearer {internal_service_token}"}
    if owner_id is not None:
        # Percent-encoded: header values must be latin-1, and padded ids stay distinct from bare ones
        headers[SCHEDULE_OWNER_HEADER] = quote(owner_id, safe="")
    if idempotency_key is not None:
        # The run routes cap this at 512 characters; the monitor's key is an id
        # and an integer, so it is nowhere near that.
        headers["Idempotency-Key"] = idempotency_key
    return headers


def build_run_delivery_request(
    payload: Optional[Dict[str, Any]],
    owner_id: Optional[str],
    *,
    source: str,
    drop_fields: Iterable[str] = (),
) -> Dict[str, str]:
    """Build the form body for a background run submitted on an owner's behalf.

    Args:
        payload: The caller-supplied payload stored on the schedule or monitor.
        owner_id: The row's owner. Wins over anything the payload says.
        source: What to name in the warning when metadata has to be dropped.
        drop_fields: Extra keys the caller sets itself afterwards (the monitor
            builds its own ``message``, the scheduler does not).

    "version" is stripped because an internal delivery always fires the live
    published version; a payload-smuggled pin must not turn one into a
    draft-preview channel. The same pin also rides in run metadata, which the
    run-start route carries onto the run, so it is scrubbed from there and from
    the top level. The rest of RESERVED_RUN_METADATA_KEYS -- the dispatch
    lineage pair -- gets the same treatment: stored payloads are writable, so
    they are an inbound channel for a forged chain.
    """
    sanitized = dict(payload or {})

    raw_metadata = sanitized.get("metadata")
    if isinstance(raw_metadata, str):
        try:
            raw_metadata = json.loads(raw_metadata)
        except (ValueError, TypeError):
            raw_metadata = None
    if isinstance(raw_metadata, dict):
        sanitized["metadata"] = {k: v for k, v in raw_metadata.items() if k not in RESERVED_RUN_METADATA_KEYS}
    elif "metadata" in sanitized:
        # The run routes accept only a JSON object here and answer 4xx for
        # anything else. A row stored with non-object metadata would then fail on
        # every delivery, forever, with nothing able to repair it -- so drop the
        # field rather than send a request that can only fail.
        sanitized.pop("metadata")
        log_warning(f"{source}: dropping non-object metadata from the payload; run endpoints accept a JSON object.")

    reserved = ("stream", "background", "version", *RESERVED_RUN_METADATA_KEYS, *drop_fields)
    form = {k: to_form_value(v) for k, v in sanitized.items() if k not in reserved}
    form["stream"] = "false"
    form["background"] = "true"

    # The owner wins over the user-controlled payload: a crafted row must not run as another user
    form.pop("user_id", None)
    if owner_id is not None:
        form["user_id"] = owner_id
    return form


def split_run_endpoint(match: Any) -> Tuple[str, str]:
    """The (resource_type, resource_id) of a matched run endpoint."""
    return match.group(1), match.group(2)
