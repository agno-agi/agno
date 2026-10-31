from pathlib import Path

import pytest

from agno.fs import FileSystem
from agno.fs.local import LocalFileSystem


@pytest.fixture
def local_backend(tmp_path: Path) -> LocalFileSystem:
    return LocalFileSystem(root=tmp_path)


@pytest.fixture
def fs(local_backend: LocalFileSystem) -> FileSystem:
    return FileSystem(backend=local_backend, namespace="radar")
