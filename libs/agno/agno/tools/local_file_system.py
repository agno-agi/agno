"""Deprecated: LocalFileSystemTools has been consolidated into FileTools.

Use FileTools instead:

    from agno.tools.file import FileTools

    agent = Agent(tools=[FileTools()])
"""

import warnings


class LocalFileSystemTools:
    """Deprecated: Use FileTools instead."""

    def __init__(self, *args, **kwargs):
        warnings.warn(
            "LocalFileSystemTools is deprecated. Use FileTools instead. See: from agno.tools.file import FileTools",
            DeprecationWarning,
            stacklevel=2,
        )
        raise ImportError("LocalFileSystemTools has been removed. Use FileTools instead.")
