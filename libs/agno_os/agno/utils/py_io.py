from pathlib import Path
from typing import Dict, Optional


def get_python_objects_from_module(module_path: Path) -> Dict:
    """Returns a dictionary of python objects from a module"""
    import importlib.util
    from importlib.machinery import ModuleSpec

    # https://docs.python.org/3/library/importlib.html#importing-a-source-file-directly
    # Create a ModuleSpec
    module_spec: Optional[ModuleSpec] = importlib.util.spec_from_file_location("module", module_path)
    # Using the ModuleSpec create a module
    if module_spec:
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)  # type: ignore
        return module.__dict__
    else:
        return {}
