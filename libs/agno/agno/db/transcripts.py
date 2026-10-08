"""Shared serialization for opaque external-agent transcripts."""

import json
from threading import Lock
from time import time_ns
from typing import Any, Dict, List, Optional
from uuid import uuid4

_position_lock = Lock()
_last_position = 0


def transcript_rows(
    project_key: str, session_id: str, entries: List[Dict[str, Any]], subpath: Optional[str]
) -> List[Dict[str, Any]]:
    """Assign write times and preserve append order within a process."""
    global _last_position
    with _position_lock:
        created_at = time_ns() // 1_000_000
        # Reserve enough millisecond buckets for large batches and same-tick calls.
        created_at = max(created_at, _last_position // 1000 + 1)
        rows: List[Dict[str, Any]] = [
            dict(
                entry_id=entry.get("uuid") or str(uuid4()),
                project_key=project_key,
                session_id=session_id,
                subpath=subpath,
                position=created_at * 1000 + index,
                entry=json.dumps(entry),
                created_at=created_at,
            )
            for index, entry in enumerate(entries)
        ]
        if rows:
            _last_position = rows[-1]["position"]
        return rows
