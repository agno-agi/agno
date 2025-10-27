from typing import Dict, List
import inspect
import re
import importlib

from agno.knowledge.reader.reader_factory import ReaderFactory
from agno.knowledge.types import ContentType
from agno.utils.log import log_debug


def _get_chunker_class(strategy_type):
    """Get the chunker class for a given strategy type without instantiation."""
    from agno.knowledge.chunking.strategy import ChunkingStrategyType

    # Map strategy types to their corresponding classes
    strategy_class_mapping = {
        ChunkingStrategyType.AGENTIC_CHUNKER: lambda: _import_class(
            "agno.knowledge.chunking.agentic", "AgenticChunking"
        ),
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
    """Get information about a reader without instantiating it."""
    try:
        # Get the reader class directly without instantiation
        reader_class = _get_reader_class(reader_key)
        
        # Call class methods directly
        supported_strategies = reader_class.get_supported_chunking_strategies()
        supported_content_types = reader_class.get_supported_content_types()

        # Get description from the factory method's config
        description = _get_reader_description(reader_key)

        return {
            "id": reader_key,
            "name": "".join(word.capitalize() for word in reader_key.split("_")) + "Reader",
            "description": description,
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


def _get_reader_class(reader_key: str):
    """Get the reader class without instantiating it using auto-discovery."""
    # First check if the reader key is valid by checking ReaderFactory
    method_name = f"_get_{reader_key}_reader"
    if not hasattr(ReaderFactory, method_name):
        raise ValueError(f"Unknown reader: {reader_key}")
    
    # Use naming conventions to construct module and class names
    # Convert reader_key to module name: "field_labeled_csv" -> "field_labeled_csv_reader"
    module_name = f"agno.knowledge.reader.{reader_key}_reader"
    
    # Convert reader_key to class name: "field_labeled_csv" -> "FieldLabeledCsvReader"
    # Handle special cases and convert to PascalCase
    class_name = _reader_key_to_class_name(reader_key)
    
    try:
        # Dynamically import the class
        module = importlib.import_module(module_name)
        reader_class = getattr(module, class_name)
        
        return reader_class
        
    except (ImportError, AttributeError) as e:
        raise ValueError(f"Failed to import reader class for {reader_key}: {str(e)}")


def _reader_key_to_class_name(reader_key: str) -> str:
    """Convert reader key to class name using naming conventions."""
    # Special case mappings for readers that use acronym capitalization
    # These maintain backward compatibility with existing public API class names
    special_cases = {
        "pptx": "PPTXReader",    # PPTX acronym is all caps
        "csv": "CSVReader",      # CSV acronym is all caps  
        "json": "JSONReader",    # JSON acronym is all caps
        "pdf": "PDFReader",      # PDF acronym is all caps
    }
    
    if reader_key in special_cases:
        return special_cases[reader_key]
    
    # Default: convert snake_case to PascalCase and add "Reader" suffix
    # Examples: "field_labeled_csv" -> "FieldLabeledCsvReader"
    #          "web_search" -> "WebSearchReader"  
    #          "docx" -> "DocxReader"
    words = reader_key.split("_")
    class_name = "".join(word.capitalize() for word in words) + "Reader"
    
    return class_name


def _get_reader_description(reader_key: str) -> str:
    """Get the description from the factory method's configuration."""
    try:
        # Get the factory method
        method_name = f"_get_{reader_key}_reader"
        if not hasattr(ReaderFactory, method_name):
            return f"Reader for {reader_key} files"
        
        # Use source inspection to extract the description from the config dict
        method = getattr(ReaderFactory, method_name)
        source = inspect.getsource(method)
        
        # Look for the description in the config dict
        # Pattern: "description": "Some description text"
        desc_match = re.search(r'"description":\s*"([^"]+)"', source)
        
        if desc_match:
            return desc_match.group(1)
        else:
            return f"Reader for {reader_key} files"
            
    except Exception:
        # Fallback to generic description if extraction fails
        return f"Reader for {reader_key} files"


def get_all_readers_info() -> List[Dict]:
    """Get information about all available readers."""
    readers_info = []
    keys = ReaderFactory.get_all_reader_keys()
    print(f"Keys: {keys}")
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
                "name": chunker_key,
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
