"""Time-ordered identifiers for scheduler history records."""

import time
from threading import Lock
from uuid import uuid4

_last_timestamp = 0
_lock = Lock()


def new_schedule_run_id() -> str:
    """Preserve creation order even when public timestamps have second precision.

    The nanosecond prefix orders records across workers; the local counter also
    handles equal readings and backward clock adjustments within a worker.
    UUID entropy preserves uniqueness across processes. The prefix sorts after
    legacy UUID records when their public timestamps tie. Existing history is
    retained without changing timestamp units or requiring a storage migration.
    """
    global _last_timestamp
    with _lock:
        _last_timestamp = max(time.time_ns(), _last_timestamp + 1)
        timestamp = _last_timestamp
    return f"sr_{timestamp:020d}_{uuid4()}"
