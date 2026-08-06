from pathlib import Path
from typing import Any, Optional

from agno.utils.log import logger


def pickle_object_to_file(obj: Any, file_path: Path) -> Any:
    """Pickles and saves object to file_path"""
    import pickle

    _obj_parent = file_path.parent
    if not _obj_parent.exists():
        _obj_parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("wb") as f:
        pickle.dump(obj, f)


def unpickle_object_from_file(file_path: Path, verify_class: Optional[Any] = None) -> Any:
    """Reads the contents of file_path and unpickles the binary content into an object.
    If verify_class is provided, checks if the object is an instance of that class.
    """
    import pickle

    _obj = None
    # log_debug(f"Reading {file_path}")
    if file_path.exists() and file_path.is_file():
        with file_path.open("rb") as f:
            _obj = pickle.load(f)

    if _obj and verify_class and not isinstance(_obj, verify_class):
        logger.warning(f"Object does not match {verify_class}")
        _obj = None

    return _obj
