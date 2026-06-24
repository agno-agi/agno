"""Backward-compatibility stub. Use agno.tools.google.gmail instead."""

import warnings

warnings.warn(
    "Importing from 'agno.tools.gmail' is deprecated. Use 'from agno.tools.google.gmail import GmailTools' instead.",
    DeprecationWarning,
    stacklevel=2,
)

from agno.tools.google.gmail import *  # noqa: F401, F403, E402
from agno.tools.google.gmail import GmailTools  # noqa: F811, E402

__all__ = ["GmailTools"]
