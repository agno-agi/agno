"""Backward-compatibility stub. Use agno.tools.google.sheets instead."""

import warnings

warnings.warn(
    "Importing from 'agno.tools.googlesheets' is deprecated. "
    "Use 'from agno.tools.google.sheets import GoogleSheetsTools' instead.",
    DeprecationWarning,
    stacklevel=2,
)

from agno.tools.google.sheets import *  # noqa: F401, F403, E402
from agno.tools.google.sheets import GoogleSheetsTools  # noqa: F811, E402

__all__ = ["GoogleSheetsTools"]
