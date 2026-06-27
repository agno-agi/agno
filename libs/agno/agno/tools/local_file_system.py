from pathlib import Path
from typing import Any, List, Optional
from uuid import uuid4

from agno.tools import Toolkit
from agno.tools._security import resolve_within
from agno.utils.log import log_debug, log_error


class LocalFileSystemTools(Toolkit):
    """Write and read files on the local filesystem.

    Security notes (hardened build):

    * The caller cannot escape ``target_directory``: both the
      optional ``directory`` parameter and the resolved final path
      must stay inside it. Symlinks are resolved before the
      containment check via
      :func:`agno.tools._security.resolve_within`.
    * ``mkdir(parents=True)`` is only ever called under
      ``target_directory``; arbitrary directory trees cannot be
      created on the host.
    * Filenames with embedded path separators (``/`` or ``\\``) are
      rejected — subdirectories must be requested explicitly via
      ``directory``.

    Args:
        target_directory: Base directory for all reads / writes.
            Created if it does not exist. Defaults to the current
            working directory.
        default_extension: Extension used when the caller does not
            provide one. The leading dot is optional.
        enable_write_file: Register :meth:`write_file`.
    """

    def __init__(
        self,
        target_directory: Optional[str] = None,
        default_extension: str = "txt",
        enable_write_file: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.target_directory: str = target_directory or str(Path.cwd())
        self.default_extension: str = default_extension.lstrip(".")

        target_path = Path(self.target_directory).resolve()
        target_path.mkdir(parents=True, exist_ok=True)
        self._base: Path = target_path

        tools: List[Any] = []
        if all or enable_write_file:
            tools.append(self.write_file)

        super().__init__(name="write_to_local", tools=tools, **kwargs)

    def write_file(
        self,
        content: str,
        filename: Optional[str] = None,
        directory: Optional[str] = None,
        extension: Optional[str] = None,
    ) -> str:
        """Write ``content`` to a file under ``target_directory``.

        Args:
            content: Text to write.
            filename: File name without path separators. Defaults to
                a UUID when omitted.
            directory: Subdirectory relative to ``target_directory``.
                Absolute paths and any path that escapes the base
                are rejected.
            extension: File extension. Falls back to
                ``default_extension``.

        Returns:
            The absolute path of the created file on success, or an
            error string.
        """
        try:
            filename = filename or str(uuid4())
            if any(sep in filename for sep in ("/", "\\")):
                return "Error: filename must not contain path separators"
            if "." in filename:
                path_obj = Path(filename)
                filename = path_obj.stem
                extension = extension or path_obj.suffix.lstrip(".")

            log_debug(f"Writing file to local system: {filename}")

            extension = (extension or self.default_extension).lstrip(".")

            target_sub = directory if directory else "."
            ok, dir_path = resolve_within(target_sub, self._base)
            if not ok:
                log_error(f"Refusing to write outside target directory: {directory!r}")
                return "Error: directory is outside the configured target_directory"
            dir_path.mkdir(parents=True, exist_ok=True)

            full_filename = f"{filename}.{extension}"
            file_path = dir_path / full_filename
            ok2, final = resolve_within(str(file_path), self._base)
            if not ok2:
                log_error(f"Refusing to write outside target directory after resolution: {file_path!r}")
                return "Error: final path is outside the configured target_directory"

            final.write_text(content)
            return f"Successfully wrote file to: {final}"

        except Exception as e:
            error_msg = f"Failed to write file: {str(e)}"
            log_error(error_msg)
            return f"Error: {error_msg}"

    def read_file(self, filename: str, directory: Optional[str] = None) -> str:
        """Read a file contained within ``target_directory``.

        Not registered as an agent tool by default; exposed for
        programmatic use alongside :meth:`write_file`.

        Args:
            filename: Name of the file; path separators are rejected.
            directory: Subdirectory relative to ``target_directory``.

        Returns:
            The file's contents on success, or an error string.
        """
        target_sub = directory if directory else "."
        ok, dir_path = resolve_within(target_sub, self._base)
        if not ok:
            log_error(f"Refusing to read outside target directory: {directory!r}")
            return "Error: directory is outside the configured target_directory"

        if "/" in filename or "\\" in filename:
            return "Error: filename must not contain path separators"

        file_path = dir_path / filename
        ok2, final = resolve_within(str(file_path), self._base)
        if not ok2:
            log_error(f"Refusing to read outside target directory after resolution: {file_path!r}")
            return "Error: path is outside the configured target_directory"
        if not final.exists():
            return f"File not found: {final}"
        return final.read_text()
