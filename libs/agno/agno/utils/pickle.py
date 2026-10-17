import pickle
from pathlib import Path
from typing import Any, Optional

from agno.utils.log import logger


def pickle_object_to_file(obj: Any, file_path: Path) -> Any:
    """Pickles and saves object to file_path"""
    _obj_parent = file_path.parent
    if not _obj_parent.exists():
        _obj_parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("wb") as _file:
        pickle.dump(obj, _file)


# Modules whose globals can execute arbitrary code when referenced during
# unpickling. Unpickling untrusted data with unrestricted access to them is
# CWE-502 (Deserialization of Untrusted Data). See:
# https://docs.python.org/3/library/pickle.html#restricting-globals
_FORBIDDEN_PICKLE_MODULES = frozenset(
    {
        "atexit",
        "builtins",
        "ctypes",
        "functools",
        "gc",
        "importlib",
        "multiprocessing",
        "os",
        "posix",
        "pty",
        "shutil",
        "signal",
        "socket",
        "subprocess",
        "sys",
        "threading",
    }
)


class RestrictedUnpickler(pickle.Unpickler):
    """Unpickler that rejects globals from modules which can execute arbitrary code.

    Used to mitigate CWE-502 when loading objects from files that may be
    attacker-controlled (e.g. shared storage or agent workspace exports).
    """

    def find_class(self, module: str, name: str) -> Any:
        if module in _FORBIDDEN_PICKLE_MODULES:
            raise pickle.UnpicklingError(
                f"global '{module}.{name}' is forbidden for security (CWE-502)"
            )
        return super().find_class(module, name)


def unpickle_object_from_file(file_path: Path, verify_class: Optional[Any] = None) -> Any:
    """Reads the contents of file_path and unpickles the binary content into an object.
    If verify_class is provided, checks if the object is an instance of that class.

    Loading is performed with :class:`RestrictedUnpickler`, which rejects globals
    from modules that can execute arbitrary code (``os``, ``subprocess``, ``builtins``, ...),
    mitigating CWE-502 (Deserialization of Untrusted Data) on attacker-controlled files.
    """
    _obj = None
    if file_path.exists() and file_path.is_file():
        with file_path.open("rb") as _file:
            _obj = RestrictedUnpickler(_file).load()

    if _obj and verify_class and not isinstance(_obj, verify_class):
        logger.warning(f"Object does not match {verify_class}")
        _obj = None

    return _obj
