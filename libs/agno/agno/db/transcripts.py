"""Shared serialization for opaque external-agent transcripts."""

import hashlib
import json
from time import time_ns
from typing import Any, Dict, List, Optional


def transcript_rows(
    framework: str,
    project_key: str,
    session_id: str,
    subpath: Optional[str],
    agno_session_id: str,
    entries: List[Dict[str, Any]],
    position_after: int,
) -> List[Dict[str, Any]]:
    """Number entries after the transcript's last stored position."""
    created_at = time_ns() // 1_000_000
    return [
        dict(
            framework=framework,
            project_key=project_key,
            session_id=session_id,
            subpath=subpath or "",
            position=position_after + index + 1,
            entry_uuid=entry.get("uuid") or None,
            entry=json.dumps(entry),
            agno_session_id=agno_session_id,
            created_at=created_at,
        )
        for index, entry in enumerate(entries)
    ]


def transcript_lock_id(framework: str, project_key: str, session_id: str, subpath: Optional[str]) -> int:
    """Stable PostgreSQL advisory-lock key for one transcript."""
    key = json.dumps([framework, project_key, session_id, subpath or ""]).encode()
    return int.from_bytes(hashlib.sha256(key).digest()[:8], byteorder="big", signed=True)
