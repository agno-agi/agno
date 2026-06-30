from typing import Any, Dict, List, Optional

from agno.knowledge.reader.base import Reader
from agno.knowledge.reader.reader_factory import ReaderFactory
from agno.knowledge.types import ContentType
from agno.utils.log import log_debug

RESERVED_AGNO_KEY = "_agno"


def merge_user_metadata(
    existing: Optional[Dict[str, Any]],
    incoming: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Deep-merge two metadata dicts, preserving the ``_agno`` sub-key from both sides.

    Top-level keys from *incoming* overwrite those in *existing* (except ``_agno``).
    Keys inside ``_agno`` are merged individually so that info added
    after initial source info is not lost.
    """
    if not existing:
        return incoming
    if not incoming:
        return existing

    merged = dict(existing)
    for key, value in incoming.items():
        if key == RESERVED_AGNO_KEY:
            old_agno = merged.get(RESERVED_AGNO_KEY, {}) or {}
            new_agno = value if isinstance(value, dict) else {}
            merged[RESERVED_AGNO_KEY] = {**old_agno, **new_agno}
        else:
            merged[key] = value
    return merged


def set_agno_metadata(
    metadata: Optional[Dict[str, Any]],
    key: str,
    value: Any,
) -> Dict[str, Any]:
    """Set a key under the reserved ``_agno`` namespace in metadata."""
    if metadata is None:
        metadata = {}
    agno_meta = metadata.get(RESERVED_AGNO_KEY, {}) or {}
    agno_meta[key] = value
    metadata[RESERVED_AGNO_KEY] = agno_meta
    return metadata


def get_agno_metadata(
    metadata: Optional[Dict[str, Any]],
    key: str,
) -> Any:
    """Get a key from the reserved ``_agno`` namespace in metadata."""
    if not metadata:
        return None
    agno_meta = metadata.get(RESERVED_AGNO_KEY)
    if not isinstance(agno_meta, dict):
        return None
    return agno_meta.get(key)


def strip_agno_metadata(
    metadata: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Return a copy of *metadata* without the reserved ``_agno`` key.

    Useful before sending metadata to the vector DB where only
    user-defined fields should be searchable.
    """
    if not metadata:
        return metadata
    return {k: v for k, v in metadata.items() if k != RESERVED_AGNO_KEY}


def _get_chunker_class(strategy_type):
    """Get the chunker class for a given strategy type without instantiation."""
    from agno.knowledge.chunking.strategy import ChunkingStrategyType

    # Map strategy types to their corresponding classes
    strategy_class_mapping = {
        ChunkingStrategyType.AGENTIC_CHUNKER: lambda: _import_class(
            "agno.knowledge.chunking.agentic", "AgenticChunking"
        ),
        ChunkingStrategyType.CODE_CHUNKER: lambda: _import_class("agno.knowledge.chunking.code", "CodeChunking"),
        ChunkingStrategyType.DOCUMENT_CHUNKER: lambda: _import_class(
            "agno.knowledge.chunking.document", "DocumentChunking"
        ),
        ChunkingStrategyType.RECURSIVE_CHUNKER: lambda: _import_class(
            "agno.knowledge.chunking.recursive", "RecursiveChunking"
        ),
        ChunkingStrategyType.SEMANTIC_CHUNKER: lambda: _import_class(
            "agno.knowledge.chunking.semantic", "SemanticChunking"
        ),
        ChunkingStrategyType.FIXED_SIZE_CHUNKER: lambda: _import_class(
            "agno.knowledge.chunking.fixed", "FixedSizeChunking"
        ),
        ChunkingStrategyType.ROW_CHUNKER: lambda: _import_class("agno.knowledge.chunking.row", "RowChunking"),
        ChunkingStrategyType.MARKDOWN_CHUNKER: lambda: _import_class(
            "agno.knowledge.chunking.markdown", "MarkdownChunking"
        ),
    }

    if strategy_type not in strategy_class_mapping:
        raise ValueError(f"Unknown strategy type: {strategy_type}")

    return strategy_class_mapping[strategy_type]()


def _import_class(module_name: str, class_name: str):
    """Dynamically import a class from a module."""
    import importlib

    module = importlib.import_module(module_name)
    return getattr(module, class_name)


def get_reader_info(reader_key: str) -> Dict:
    """Get information about a reader without instantiating it.

    Uses class methods and static metadata from ReaderFactory to avoid
    the overhead of creating reader instances.
    """
    try:
        # Get the reader CLASS without instantiation
        reader_class = ReaderFactory.get_reader_class(reader_key)

        # Get metadata from static registry (no instantiation needed)
        metadata = ReaderFactory.READER_METADATA.get(reader_key, {})

        # Call class methods directly (no instance needed)
        supported_strategies = reader_class.get_supported_chunking_strategies()  # type: ignore[attr-defined]
        supported_content_types = reader_class.get_supported_content_types()  # type: ignore[attr-defined]

        return {
            "id": reader_key,
            "name": metadata.get("name", reader_class.__name__),
            "description": metadata.get("description", f"{reader_class.__name__} reader"),
            "chunking_strategies": [strategy.value for strategy in supported_strategies],
            "content_types": [ct.value for ct in supported_content_types],
        }
    except ImportError as e:
        # Skip readers with missing dependencies
        raise ValueError(f"Reader '{reader_key}' has missing dependencies: {str(e)}")
    except Exception as e:
        raise ValueError(f"Unknown reader: {reader_key}. Error: {str(e)}")


def get_reader_info_from_instance(reader: Reader, reader_id: str) -> Dict:
    """Get information about a reader instance."""
    try:
        reader_class = reader.__class__
        supported_strategies = reader_class.get_supported_chunking_strategies()
        supported_content_types = reader_class.get_supported_content_types()

        return {
            "id": reader_id,
            "name": getattr(reader, "name", reader_class.__name__),
            "description": getattr(reader, "description", f"Custom {reader_class.__name__}"),
            "chunking_strategies": [strategy.value for strategy in supported_strategies],
            "content_types": [ct.value for ct in supported_content_types],
        }
    except Exception as e:
        raise ValueError(f"Failed to get info for reader '{reader_id}': {str(e)}")


def get_all_readers_info(knowledge_instance: Optional[Any] = None) -> List[Dict]:
    """Get information about all available readers, including custom readers from a Knowledge instance.

    Custom readers are added first and take precedence over factory readers with the same ID.

    Args:
        knowledge_instance: Optional Knowledge instance to include custom readers from.

    Returns:
        List of reader info dictionaries (custom readers first, then factory readers).
    """
    readers_info = []
    seen_ids: set = set()

    # 1. Add custom readers FIRST (they take precedence over factory readers)
    if knowledge_instance is not None:
        custom_readers = knowledge_instance.get_readers()
        if isinstance(custom_readers, dict):
            for reader_id, reader in custom_readers.items():
                try:
                    reader_info = get_reader_info_from_instance(reader, reader_id)
                    readers_info.append(reader_info)
                    seen_ids.add(reader_id)
                except ValueError as e:
                    log_debug(f"Skipping custom reader '{reader_id}': {e}")
                    continue

    # 2. Add factory readers (skip if custom reader with same ID already exists)
    keys = ReaderFactory.get_all_reader_keys()
    for key in keys:
        if key in seen_ids:
            # Custom reader with this ID already added, skip factory version
            continue
        try:
            reader_info = get_reader_info(key)
            readers_info.append(reader_info)
        except ValueError as e:
            # Skip readers with missing dependencies or other issues
            log_debug(f"Skipping reader '{key}': {e}")
            continue

    return readers_info


def get_content_types_to_readers_mapping(knowledge_instance: Optional[Any] = None) -> Dict[str, List[str]]:
    """Get mapping of content types to list of reader IDs that support them.

    Args:
        knowledge_instance: Optional Knowledge instance to include custom readers from.

    Returns:
        Dictionary mapping content type strings (ContentType enum values) to list of reader IDs.
    """
    content_type_mapping: Dict[str, List[str]] = {}
    readers_info = get_all_readers_info(knowledge_instance)
    for reader_info in readers_info:
        reader_id = reader_info["id"]
        content_types = reader_info.get("content_types", [])

        for content_type in content_types:
            if content_type not in content_type_mapping:
                content_type_mapping[content_type] = []
            # Avoid duplicates
            if reader_id not in content_type_mapping[content_type]:
                content_type_mapping[content_type].append(reader_id)

    return content_type_mapping


def get_chunker_info(chunker_key: str) -> Dict:
    """Get information about a chunker without instantiating it."""
    try:
        # Use chunking strategies directly
        from agno.knowledge.chunking.strategy import ChunkingStrategyType

        try:
            # Use the chunker key directly as the strategy type value
            strategy_type = ChunkingStrategyType.from_string(chunker_key)

            # Get class directly without instantiation
            chunker_class = _get_chunker_class(strategy_type)

            # Extract class information
            class_name = chunker_class.__name__
            docstring = chunker_class.__doc__ or f"{class_name} chunking strategy"

            # Check class __init__ signature for chunk_size and overlap parameters
            metadata = {}
            import inspect

            try:
                sig = inspect.signature(chunker_class.__init__)
                param_names = set(sig.parameters.keys())

                # If class has chunk_size or max_chunk_size parameter, set default chunk_size
                if "chunk_size" in param_names or "max_chunk_size" in param_names:
                    metadata["chunk_size"] = 5000

                # If class has overlap parameter, set default overlap
                if "overlap" in param_names:
                    metadata["chunk_overlap"] = 0
            except Exception:
                # If we can't inspect, skip metadata
                pass

            return {
                "key": chunker_key,
                "class_name": class_name,
                "name": chunker_key,
                "description": docstring.strip(),
                "strategy_type": strategy_type.value,
                "metadata": metadata,
            }
        except ValueError:
            raise ValueError(f"Unknown chunker key: {chunker_key}")

    except ImportError as e:
        # Skip chunkers with missing dependencies
        raise ValueError(f"Chunker '{chunker_key}' has missing dependencies: {str(e)}")
    except Exception as e:
        raise ValueError(f"Unknown chunker: {chunker_key}. Error: {str(e)}")


def get_all_content_types() -> List[ContentType]:
    """Get all available content types as ContentType enums."""
    return list(ContentType)


def get_all_chunkers_info() -> List[Dict]:
    """Get information about all available chunkers."""
    chunkers_info = []

    from agno.knowledge.chunking.strategy import ChunkingStrategyType

    keys = [strategy_type.value for strategy_type in ChunkingStrategyType]

    for key in keys:
        try:
            chunker_info = get_chunker_info(key)
            chunkers_info.append(chunker_info)
        except ValueError as e:
            log_debug(f"Skipping chunker '{key}': {e}")
            continue
    return chunkers_info
