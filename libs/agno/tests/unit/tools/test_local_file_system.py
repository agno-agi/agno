from pathlib import Path
import tempfile

import pytest

from agno.tools.local_file_system import LocalFileSystemTools


def _normalize_write_input(
    directory: str | None,
    filename: str,
    extension: str | None,
) -> Path:
    if "." in filename:
        parsed = Path(filename)
        filename = parsed.stem
        extension = extension or parsed.suffix.lstrip(".")
    extension = (extension or "txt").lstrip(".")
    safe_directory = directory or "."
    return Path(safe_directory) / f"{filename}.{extension}"


def _generate_local_file_system_cases():
    for index in range(200):
        if index < 100:
            directory = [".", "notes", "notes/subdir", "safe/nested", "safe/."][index % 5]
            filename = f"file_{index}" if index % 2 == 0 else f"path/name_{index}"
            extension = "md" if index % 3 == 0 else None
            yield ("safe", directory, filename, extension)
        else:
            unsafe_index = index - 100
            if unsafe_index % 5 == 0:
                directory = "../outside"
                filename = f"escape_{unsafe_index}"
                extension = "txt"
            elif unsafe_index % 5 == 1:
                directory = "safe/../../outside"
                filename = f"../../evil_{unsafe_index}"
                extension = None
            elif unsafe_index % 5 == 2:
                directory = "safe"
                filename = f"../bad_{unsafe_index}"
                extension = "md"
            elif unsafe_index % 5 == 3:
                directory = f"/tmp/rogue_{unsafe_index}"
                filename = f"evil_{unsafe_index}"
                extension = None
            else:
                directory = "safe"
                filename = "C:\\tmp\\bad"
                extension = "txt"
            yield ("unsafe", directory, filename, extension)


@pytest.mark.parametrize("kind, directory, filename, extension", list(_generate_local_file_system_cases()))
def test_local_file_system_write_file_handles_many_paths(kind, directory, filename, extension):
    with tempfile.TemporaryDirectory() as target_directory:
        tool = LocalFileSystemTools(target_directory=target_directory)
        baseline = set(p.relative_to(target_directory) for p in Path(target_directory).rglob("*"))
        result = tool.write_file(content="payload", filename=filename, directory=directory, extension=extension)

        if kind == "safe":
            assert result.startswith("Successfully wrote file to:")
            written_path = Path(target_directory) / _normalize_write_input(directory, filename, extension)
            assert written_path.exists()
            assert written_path.read_text() == "payload"
            assert set(p.relative_to(target_directory) for p in Path(target_directory).rglob("*")) != baseline
        else:
            assert result.startswith("Error")
            assert set(p.relative_to(target_directory) for p in Path(target_directory).rglob("*")) == baseline
