"""Base loader class with shared utilities for all content loaders.

Provides common helpers for:
- Computing content names for files
- Creating Content entries
- Building metadata dictionaries
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from agno.knowledge.content import Content, ContentStatus
from agno.utils.string import generate_id


@dataclass
class FileToProcess:
    """Represents a file identified for processing."""

    path: str
    name: str
    size: Optional[int] = None
    content_type: Optional[str] = None


class BaseLoader:
    """Base class with shared loader utilities.

    This class provides common methods used by all content loaders to reduce
    code duplication between sync and async implementations.

    Methods that call self._build_content_hash() assume they are mixed into
    a class that provides this method (e.g., Knowledge via RemoteKnowledge).
    """

    def _compute_content_name(
        self,
        file_path: str,
        file_name: str,
        base_name: Optional[str],
        root_path: str,
        is_folder_upload: bool,
    ) -> str:
        """Compute the content name for a file.

        Args:
            file_path: Full path to the file
            file_name: Name of the file
            base_name: User-provided base name for the content
            root_path: Root path of the upload (for computing relative paths)
            is_folder_upload: Whether this is part of a folder upload

        Returns:
            The computed content name
        """
        if is_folder_upload:
            relative_path = file_path
            if root_path and file_path.startswith(root_path + "/"):
                relative_path = file_path[len(root_path) + 1 :]
            return f"{base_name}/{relative_path}" if base_name else file_path
        return base_name or file_name

    def _create_content_entry_for_folder(
        self,
        content: Content,
        content_name: str,
        virtual_path: str,
        metadata: Dict[str, Any],
        file_type: str,
    ) -> Content:
        """Create a new Content entry for a file in a folder upload.

        Args:
            content: Original content object (used for description)
            content_name: Name for the new content entry
            virtual_path: Virtual path for hashing
            metadata: Metadata dictionary
            file_type: Type of file (e.g., 'github', 'azure_blob')

        Returns:
            New Content entry with hash and ID set
        """
        entry = Content(
            name=content_name,
            description=content.description,
            path=virtual_path,
            status=ContentStatus.PROCESSING,
            metadata=metadata,
            file_type=file_type,
        )
        entry.content_hash = self._build_content_hash(entry)  # type: ignore[attr-defined]
        entry.id = generate_id(entry.content_hash)
        return entry

    def _update_content_entry_for_single_file(
        self,
        content: Content,
        virtual_path: str,
        metadata: Dict[str, Any],
        file_type: str,
    ) -> Content:
        """Update an existing Content entry for a single file upload.

        Args:
            content: Original content object to update
            virtual_path: Virtual path for hashing
            metadata: Metadata dictionary
            file_type: Type of file (e.g., 'github', 'azure_blob')

        Returns:
            Updated Content entry with hash and ID set if not already present
        """
        content.path = virtual_path
        content.status = ContentStatus.PROCESSING
        content.metadata = metadata
        content.file_type = file_type
        if not content.content_hash:
            content.content_hash = self._build_content_hash(content)  # type: ignore[attr-defined]
        if not content.id:
            content.id = generate_id(content.content_hash)
        return content

    def _create_content_entry(
        self,
        content: Content,
        content_name: str,
        virtual_path: str,
        metadata: Dict[str, Any],
        file_type: str,
        is_folder_upload: bool,
    ) -> Content:
        """Create or update a Content entry for a file.

        For folder uploads, creates a new Content entry.
        For single file uploads, updates the original Content object.

        Args:
            content: Original content object
            content_name: Name for the content entry
            virtual_path: Virtual path for hashing
            metadata: Metadata dictionary
            file_type: Type of file (e.g., 'github', 'azure_blob')
            is_folder_upload: Whether this is part of a folder upload

        Returns:
            Content entry with hash and ID set
        """
        if is_folder_upload:
            return self._create_content_entry_for_folder(content, content_name, virtual_path, metadata, file_type)
        return self._update_content_entry_for_single_file(content, virtual_path, metadata, file_type)

    def _merge_metadata(
        self,
        provider_metadata: Dict[str, str],
        user_metadata: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Merge provider metadata with user-provided metadata.

        User metadata takes precedence over provider metadata.

        Args:
            provider_metadata: Metadata from the provider (e.g., GitHub, Azure)
            user_metadata: User-provided metadata

        Returns:
            Merged metadata dictionary
        """
        return {**provider_metadata, **(user_metadata or {})}

    def _files_to_dict_list(self, files: List[FileToProcess]) -> List[Dict[str, Any]]:
        """Convert FileToProcess objects to dict list for compatibility.

        Args:
            files: List of FileToProcess objects

        Returns:
            List of dictionaries with file info
        """
        return [
            {
                "path": f.path,
                "name": f.name,
                "size": f.size,
                "content_type": f.content_type,
            }
            for f in files
        ]
