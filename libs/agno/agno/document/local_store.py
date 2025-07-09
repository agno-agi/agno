import json
from hashlib import md5
from pathlib import Path
from typing import Dict, Generator, Optional, Tuple

from agno.document.store import Store
from agno.knowledge.source import Source


class LocalStore(Store):
    ...
    # """
    # Simple local filesystem implementation of DocumentStore.
    # Documents are stored as JSON files in the specified directory.
    # """

    def __init__(
        self, name: str, description: str, storage_path: str, read_from_store: bool = False, copy_to_store: bool = False
    ):
        self.name = name
        self.description = description
        self.storage_path = storage_path
        self.read_from_store = read_from_store
        self.copy_to_store = copy_to_store

        # Initialize storage path
        if self.storage_path is None:
            raise ValueError("storage_path is required")
        self._storage_path = Path(self.storage_path)
        self._storage_path.mkdir(parents=True, exist_ok=True)

    def _get_source_file_path(self, source_id: str) -> Path:
        """Get the file path for a source by ID."""
        return self._storage_path / f"{source_id}.json"

    def _generate_source_hash(self, source: Source) -> str:
        """Generate a hash of the source content to be used as the source ID."""
        cleaned_content = source.content.replace("\x00", "\ufffd")
        content_hash = md5(cleaned_content.encode()).hexdigest()
        return content_hash

    def add_source(self, id: str, source: Source) -> str:
        """Add a source to the store. Returns the source ID."""
        pass

    def delete_source(self, source_id: str) -> bool:
        """Delete a source by ID. Returns True if successful."""
        file_path = self._get_document_file_path(source_id)

        if file_path.exists():
            try:
                file_path.unlink()
                return True
            except OSError:
                return False
        return False

    def delete_all_sources(self) -> bool:
        """Delete all sources from the store. Returns True if successful."""
        try:
            for file_path in self._storage_path.glob("*.json"):
                file_path.unlink()
            return True
        except OSError:
            return False

    def get_all_sources(self) -> Generator[Tuple[bytes, Dict], None, None]:
        """Get all sources from the store."""
        for file_path in self._storage_path.glob("**/*"):
            if file_path.is_file() and file_path.suffix == ".pdf":
                pdf_bytes = file_path.read_bytes()
                metadata = {
                    "name": file_path.name,
                    "file_path": str(file_path),
                    "file_type": file_path.suffix,
                    "source": self.name,
                }
                yield pdf_bytes, metadata

    def get_source_by_id(self, source_id: str) -> Optional[Source]:
        """Get a source by its ID."""
        file_path = self._get_document_file_path(source_id)

        if not file_path.exists():
            return None

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                source_dict = json.load(f)
                return Source.from_dict(source_dict)
        except (json.JSONDecodeError, FileNotFoundError):
            return None

    def get_source_by_name(self, name: str) -> Optional[Source]:
        """Get a source by its name."""
        for source in self.get_all_sources():
            if source.name == name:
                return source
        return None

    def enhance_source(self, source_id: str, **kwargs) -> bool:
        pass
