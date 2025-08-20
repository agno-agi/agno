from typing import Dict, List

from agno.knowledge.reader.reader_factory import ReaderFactory
from agno.utils.log import log_debug


def get_reader_info(reader_key: str) -> Dict:
    """Get information about a reader without instantiating it."""
    # Try to create the reader to get its info, but don't cache it
    try:
        reader_method = ReaderFactory._get_reader_method(reader_key)
        reader = reader_method()

        # Get supported chunking strategies for this reader
        supported_strategies = reader.get_supported_chunking_strategies()

        return {
            "id": reader_key,
            "name": reader_key.replace("_", " ").title() + " Reader",
            "description": f"Reads {reader_key} files",
            "chunking_strategies": supported_strategies,
        }
    except ImportError as e:
        # Skip readers with missing dependencies
        raise ValueError(f"Reader '{reader_key}' has missing dependencies: {str(e)}")
    except Exception as e:
        raise ValueError(f"Unknown reader: {reader_key}. Error: {str(e)}")


def get_all_readers_info() -> List[Dict]:
    """Get information about all available readers."""
    readers_info = []
    for key in ReaderFactory.get_all_reader_keys():
        try:
            reader_info = get_reader_info(key)
            readers_info.append(reader_info)
        except ValueError as e:
            # Skip readers with missing dependencies or other issues
            # Log the error but don't fail the entire request
            log_debug(f"Skipping reader '{key}': {e}")
            continue
    return readers_info
