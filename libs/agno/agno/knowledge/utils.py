from typing import Dict, List

from agno.knowledge.reader.reader_factory import ReaderFactory
from agno.knowledge.types import ContentType
from agno.utils.log import log_debug


def get_reader_info(reader_key: str) -> Dict:
    """Get information about a reader without instantiating it."""
    # Try to create the reader to get its info, but don't cache it
    try:
        print("getting reader info", reader_key)
        reader_class = ReaderFactory._get_reader_method(reader_key)

        # Call class methods directly - no instantiation needed!
        supported_strategies = reader_class.get_supported_chunking_strategies()
        supported_content_types = reader_class.get_supported_content_types()
        print("supported_strategies", supported_strategies)
        print("supported_content_types", supported_content_types)

        return {
            "id": reader_key,
            "name": reader_key.replace("_", " ").title() + " Reader",
            "description": f"Reads {reader_key} files",
            "chunking_strategies": supported_strategies,
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
            print(key)
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
    content_type_mapping = {}
    readers_info = get_all_readers_info()

    for reader_info in readers_info:
        reader_id = reader_info["id"]
        content_types = reader_info.get("content_types", [])

        for content_type in content_types:
            if content_type not in content_type_mapping:
                content_type_mapping[content_type] = []
            content_type_mapping[content_type].append(reader_id)

    return content_type_mapping


def get_all_content_types() -> List[ContentType]:
    """Get all available content types as ContentType enums."""
    return list(ContentType)
