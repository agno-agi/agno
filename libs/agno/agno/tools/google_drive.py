"""Backward-compatibility stub. Use agno.tools.google.drive instead."""

import warnings

warnings.warn(
    "Importing from 'agno.tools.google_drive' is deprecated. "
    "Use 'from agno.tools.google.drive import GoogleDriveTools' instead.",
    DeprecationWarning,
    stacklevel=2,
)

from agno.tools.google.drive import *  # noqa: F401, F403, E402
from agno.tools.google.drive import GoogleDriveTools  # noqa: F811, E402

__all__ = ["GoogleDriveTools"]
