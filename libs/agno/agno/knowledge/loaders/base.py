"""Base class for remote content loaders.

Defines the interface that all remote content loaders must implement,
and declares the abstract methods that are provided by the Knowledge class.
"""

from typing import TYPE_CHECKING, Any, List, Optional

from agno.knowledge.content import Content
from agno.knowledge.reader import Reader
from agno.knowledge.remote_content.config import RemoteContentConfig

if TYPE_CHECKING:
    from agno.knowledge.document import Document


class RemoteContentLoader:
    """Base class for remote content loaders.

    This class defines the interface for loading content from remote sources.
    Subclasses should implement the specific loading logic for each provider.

    The Knowledge class provides these methods via inheritance:
    - _should_skip(), _select_reader_by_uri(), _prepare_documents_for_insert()
    - _ahandle_vector_db_insert(), _handle_vector_db_insert()
    - _ainsert_contents_db(), _insert_contents_db()
    - _aupdate_content(), _update_content()
    - _build_content_hash()

    Note: This class uses protocol-style method stubs. The actual implementations
    are provided by the Knowledge class which inherits from these loaders via
    RemoteKnowledge. Python's MRO ensures Knowledge's implementations are used.
    """

    # These attributes are provided by the Knowledge subclass
    content_sources: Optional[List[RemoteContentConfig]]

    # ==========================================
    # ABSTRACT METHODS (implemented by Knowledge)
    # ==========================================
    # These are declared here for type checking and documentation.
    # The actual implementations are in Knowledge class.

    def _should_skip(self, content_hash: str, skip_if_exists: bool) -> bool:
        """Check if content should be skipped based on hash.

        Provided by Knowledge class.
        """
        ...  # type: ignore[return-value]

    def _select_reader_by_uri(self, uri: str, reader: Optional[Reader]) -> Optional[Reader]:
        """Select appropriate reader for a URI.

        Provided by Knowledge class.
        """
        ...  # type: ignore[return-value]

    def _prepare_documents_for_insert(
        self, documents: List["Document"], content_id: str, content_metadata: Optional[dict] = None
    ) -> List["Document"]:
        """Prepare documents for vector DB insertion.

        Provided by Knowledge class.
        """
        ...  # type: ignore[return-value]

    def _build_content_hash(self, content: Content) -> str:
        """Build hash for content.

        Provided by Knowledge class.
        """
        ...  # type: ignore[return-value]

    async def _ahandle_vector_db_insert(self, content: Content, read_documents: List[Any], upsert: bool) -> None:
        """Handle async vector DB insertion.

        Provided by Knowledge class.
        """
        ...

    def _handle_vector_db_insert(self, content: Content, read_documents: List[Any], upsert: bool) -> None:
        """Handle sync vector DB insertion.

        Provided by Knowledge class.
        """
        ...

    async def _ainsert_contents_db(self, content: Content) -> None:
        """Insert content into contents database (async).

        Provided by Knowledge class.
        """
        ...

    def _insert_contents_db(self, content: Content) -> None:
        """Insert content into contents database (sync).

        Provided by Knowledge class.
        """
        ...

    async def _aupdate_content(self, content: Content) -> None:
        """Update content in contents database (async).

        Provided by Knowledge class.
        """
        ...

    def _update_content(self, content: Content) -> None:
        """Update content in contents database (sync).

        Provided by Knowledge class.
        """
        ...
