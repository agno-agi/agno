from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Literal, Optional


@dataclass
class RegistryRecord:
    """Metadata for a single indexed document persisted in the registry."""

    doc_id: str
    doc_name: str
    doc_type: Literal["pdf", "md"]
    source_path: str
    structure_path: str
    indexed_at: str
    content_hash: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> RegistryRecord:
        return cls(
            doc_id=data["doc_id"],
            doc_name=data["doc_name"],
            doc_type=data["doc_type"],
            source_path=data["source_path"],
            structure_path=data["structure_path"],
            indexed_at=data["indexed_at"],
            content_hash=data.get("content_hash", ""),
        )


class DocumentRegistry:
    """Thread-safe, tenant-scoped document registry backed by a JSON file.

    All reads go through an in-memory cache; writes flush to disk atomically
    (write to temp file, then ``os.replace``).  A single ``RLock`` serialises
    both reads and writes so concurrent threads never see partial state.
    """

    def __init__(self, base_dir: Path, tenant_id: str = "default") -> None:
        self.tenant_id = tenant_id
        self._dir = Path(base_dir) / tenant_id
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "doc_registry.json"
        self._lock = threading.RLock()
        self._cache: Optional[Dict[str, RegistryRecord]] = None

    @property
    def registry_path(self) -> Path:
        return self._path

    # -- internal I/O ----------------------------------------------------------

    def _read_disk(self) -> Dict[str, RegistryRecord]:
        if not self._path.exists():
            return {}
        with self._path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
        return {k: RegistryRecord.from_dict(v) for k, v in raw.items()}

    def _write_disk(self, records: Dict[str, RegistryRecord]) -> None:
        payload = json.dumps(
            {k: asdict(v) for k, v in records.items()},
            indent=2,
            ensure_ascii=False,
        )
        fd, tmp_path = tempfile.mkstemp(dir=str(self._dir), suffix=".tmp", prefix=".registry_")
        try:
            os.write(fd, payload.encode("utf-8"))
            os.fsync(fd)
            os.close(fd)
            os.replace(tmp_path, str(self._path))
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _ensure_cache(self) -> Dict[str, RegistryRecord]:
        if self._cache is None:
            self._cache = self._read_disk()
        return self._cache

    # -- CRUD ------------------------------------------------------------------

    def upsert(self, record: RegistryRecord) -> None:
        with self._lock:
            records = self._ensure_cache()
            records[record.doc_id] = record
            self._write_disk(records)

    def get(self, doc_id: str) -> Optional[RegistryRecord]:
        with self._lock:
            return self._ensure_cache().get(doc_id)

    def get_or_raise(self, doc_id: str) -> RegistryRecord:
        record = self.get(doc_id)
        if record is None:
            raise KeyError(f"Unknown doc_id: {doc_id}")
        return record

    def delete(self, doc_id: str) -> bool:
        with self._lock:
            records = self._ensure_cache()
            if doc_id not in records:
                return False
            del records[doc_id]
            self._write_disk(records)
            return True

    def list(self) -> List[RegistryRecord]:
        with self._lock:
            records = self._ensure_cache()
        return sorted(records.values(), key=lambda r: r.indexed_at, reverse=True)

    def count(self) -> int:
        with self._lock:
            return len(self._ensure_cache())

    def find_by_hash(self, content_hash: str) -> Optional[RegistryRecord]:
        if not content_hash:
            return None
        with self._lock:
            for record in self._ensure_cache().values():
                if record.content_hash == content_hash:
                    return record
        return None

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
