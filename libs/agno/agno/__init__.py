from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agno")
except PackageNotFoundError:
    __version__ = "0.0.0"

from agno.context.manager import ContextManager

__all__ = ["__version__", "ContextManager"]
