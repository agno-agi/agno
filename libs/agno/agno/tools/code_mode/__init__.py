"""CodeMode — a persistent per-session Python kernel as a toolkit."""

from __future__ import annotations

try:
    import dill  # noqa: F401
    import ipykernel  # noqa: F401
    import jupyter_client  # noqa: F401
except ImportError:
    raise ImportError(
        "CodeMode needs `ipykernel`, `jupyter_client` and `dill`. "
        "Please install them using `pip install 'agno[code-mode]'`"
    )

from agno.tools.code_mode.code_mode import CodeMode
from agno.tools.code_mode.errors import CodeModeError, KernelBusyError, KernelDiedError, ResultTooLarge
from agno.tools.code_mode.types import CellResult

__all__ = [
    "CellResult",
    "CodeMode",
    "CodeModeError",
    "KernelBusyError",
    "KernelDiedError",
    "ResultTooLarge",
]
