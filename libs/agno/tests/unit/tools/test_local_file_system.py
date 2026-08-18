"""Unit tests for LocalFileSystemTools deprecation."""

import pytest

from agno.tools.local_file_system import LocalFileSystemTools


def test_local_file_system_tools_is_deprecated():
    """LocalFileSystemTools raises ImportError directing users to FileTools."""
    with pytest.raises(ImportError, match="Use FileTools instead"):
        LocalFileSystemTools()


def test_local_file_system_tools_with_args_is_deprecated():
    """LocalFileSystemTools raises even with arguments."""
    with pytest.raises(ImportError, match="Use FileTools instead"):
        LocalFileSystemTools(target_directory="/tmp")
