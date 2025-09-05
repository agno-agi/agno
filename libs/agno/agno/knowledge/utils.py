from typing import Dict, List

from agno.knowledge.reader.reader_factory import ReaderFactory
from agno.knowledge.types import ContentType
from agno.utils.log import log_debug


def _get_chunker_class(strategy_type):
    """Get the chunker class for a given strategy type without instantiation."""
    from agno.knowledge.chunking.strategy import ChunkingStrategyType

    # Map strategy types to their corresponding classes
    strategy_class_mapping = {
        ChunkingStrategyType.AGENTIC_CHUNKING: lambda: _import_class(
            "agno.knowledge.chunking.agentic", "AgenticChunking"
        ),
        ChunkingStrategyType.DOCUMENT_CHUNKING: lambda: _import_class(
            "agno.knowledge.chunking.document", "DocumentChunking"
        ),
        ChunkingStrategyType.RECURSIVE_CHUNKING: lambda: _import_class(
            "agno.knowledge.chunking.recursive", "RecursiveChunking"
        ),
        ChunkingStrategyType.SEMANTIC_CHUNKING: lambda: _import_class(
            "agno.knowledge.chunking.semantic", "SemanticChunking"
        ),
        ChunkingStrategyType.FIXED_SIZE_CHUNKING: lambda: _import_class(
            "agno.knowledge.chunking.fixed", "FixedSizeChunking"
        ),
        ChunkingStrategyType.ROW_CHUNKING: lambda: _import_class("agno.knowledge.chunking.row", "RowChunking"),
        ChunkingStrategyType.MARKDOWN_CHUNKING: lambda: _import_class(
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
    """Get information about a reader without instantiating it."""
    # Try to create the reader to get its info, but don't cache it
    try:
        reader_factory_method = ReaderFactory._get_reader_method(reader_key)

        # Create an instance to get the class, then call class methods
        reader_instance = reader_factory_method()
        reader_class = reader_instance.__class__

        supported_strategies = reader_class.get_supported_chunking_strategies()
        supported_content_types = reader_class.get_supported_content_types()

        return {
            "id": reader_key,
            "name": reader_key.replace("_", " ").title() + " Reader",
            "description": f"Reads {reader_key} files",
            "chunking_strategies": [
                strategy.value for strategy in supported_strategies
            ],  # Convert enums to string values
            "content_types": [ct.value for ct in supported_content_types],  # Convert enums to string values
        }
    except ImportError as e:
        # Skip readers with missing dependencies
        raise ValueError(f"Reader '{reader_key}' has missing dependencies: {str(e)}")
    except Exception as e:
        raise ValueError(f"Unknown reader: {reader_key}. Error: {str(e)}")


def get_all_readers_info() -> List[Dict]:
    """Get information about all available readers."""
    readers_info = []
    keys = ReaderFactory.get_all_reader_keys()
    for key in keys:
        try:
            reader_info = get_reader_info(key)
            readers_info.append(reader_info)
        except ValueError as e:
            # Skip readers with missing dependencies or other issues
            # Log the error but don't fail the entire request
            log_debug(f"Skipping reader '{key}': {e}")
            continue
    return readers_info


def get_content_types_to_readers_mapping() -> Dict[str, List[str]]:
    """Get mapping of content types to list of reader IDs that support them.

    Returns:
        Dictionary mapping content type strings (ContentType enum values) to list of reader IDs.
    """
    content_type_mapping: Dict[str, List[str]] = {}
    readers_info = get_all_readers_info()

    for reader_info in readers_info:
        reader_id = reader_info["id"]
        content_types = reader_info.get("content_types", [])

        for content_type in content_types:
            if content_type not in content_type_mapping:
                content_type_mapping[content_type] = []
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

            return {
                "key": chunker_key,
                "class_name": class_name,
                "name": class_name.replace("Chunking", "").replace("Strategy", ""),
                "description": docstring.strip(),
                "strategy_type": strategy_type.value,
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
