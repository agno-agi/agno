"""Backward-compatibility stub. Use agno.tools.google.maps instead."""

import warnings

warnings.warn(
    "Importing from 'agno.tools.google_maps' is deprecated. "
    "Use 'from agno.tools.google.maps import GoogleMapTools' instead.",
    DeprecationWarning,
    stacklevel=2,
)

from agno.tools.google.maps import *  # noqa: F401, F403, E402
from agno.tools.google.maps import GoogleMapTools  # noqa: F811, E402

__all__ = ["GoogleMapTools"]
