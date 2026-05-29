"""Backward-compatibility stub. Use agno.tools.google.calendar instead."""

import warnings

warnings.warn(
    "Importing from 'agno.tools.googlecalendar' is deprecated. "
    "Use 'from agno.tools.google.calendar import GoogleCalendarTools' instead.",
    DeprecationWarning,
    stacklevel=2,
)

from agno.tools.google.calendar import *  # noqa: F401, F403, E402
from agno.tools.google.calendar import GoogleCalendarTools  # noqa: F811, E402

__all__ = ["GoogleCalendarTools"]
