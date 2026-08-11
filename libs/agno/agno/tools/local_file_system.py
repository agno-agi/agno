from pathlib import Path
from typing import Any, List, Optional, Tuple
from uuid import uuid4

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error


class LocalFileSystemTools(Toolkit):
    def __init__(
        self,
        target_directory: Optional[str] = None,
        default_extension: str = "txt",
        enable_write_file: bool = True,
        enable_read_file: bool = True,
        restrict_to_base_dir: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """
        Initialize the LocalFileSystem toolkit.
        Args:
            target_directory (Optional[str]): Default directory to write files to. Creates if doesn't exist.
            default_extension (str): Default file extension to use if none specified.
            enable_write_file (bool): Enable the write_file tool.
            enable_read_file (bool): Enable the read_file tool.
            restrict_to_base_dir (bool): If True, file operations cannot escape target_directory.
        """

        self.target_directory = target_directory or str(Path.cwd())
        self.default_extension = default_extension.lstrip(".")
        self.restrict_to_base_dir = restrict_to_base_dir

        target_path = Path(self.target_directory)
        target_path.mkdir(parents=True, exist_ok=True)

        tools: List[Any] = []
        if all or enable_write_file:
            tools.append(self.write_file)
        if all or enable_read_file:
            tools.append(self.read_file)

        super().__init__(name="local_file_system", tools=tools, **kwargs)

    def check_escape(self, filename: str, directory: Optional[str] = None) -> Tuple[bool, Path]:
        """Check if the file path is within the target directory.

        Joins `directory` and `filename` into a single relative path and defers to
        Toolkit._check_path, which (when restrict_to_base_dir is True) rejects
        absolute paths, `..` traversal, and symlink escapes.

        Args:
            filename (str): The file name or relative path to check.
            directory (Optional[str]): Directory to resolve against. Uses target_directory if not provided.

        Returns:
            Tuple[bool, Path]: (is_safe, resolved_path). If not safe, returns target_directory as the path.
        """
        relative_path = str(Path(directory) / filename) if directory else filename
        return self._check_path(relative_path, Path(self.target_directory).resolve(), self.restrict_to_base_dir)

    def write_file(
        self,
        content: str,
        filename: Optional[str] = None,
        directory: Optional[str] = None,
        extension: Optional[str] = None,
    ) -> str:
        """
        Write content to a local file.
        Args:
            content (str): Content to write to the file
            filename (Optional[str]): Name of the file. Defaults to UUID if not provided
            directory (Optional[str]): Directory to write file to. Uses target_directory if not provided
            extension (Optional[str]): File extension. Uses default_extension if not provided
        Returns:
            str: Path to the created file or error message
        """
        try:
            filename = filename or str(uuid4())
            name_path = Path(filename)
            extension = (extension or name_path.suffix.lstrip(".") or self.default_extension).lstrip(".")
            full_name = str(name_path.with_name(f"{name_path.stem}.{extension}"))

            safe, file_path = self.check_escape(full_name, directory)
            if not safe:
                return f"Error: Path '{filename}' is outside the allowed base directory"

            log_debug(f"Writing file to local system: {file_path.name}")

            # Create directory if it doesn't exist
            file_path.parent.mkdir(parents=True, exist_ok=True)

            file_path.write_text(content)

            return f"Successfully wrote file to: {file_path}"

        except Exception as e:
            error_msg = f"Failed to write file: {str(e)}"
            log_error(error_msg)
            return f"Error: {error_msg}"

    def read_file(self, filename: str, directory: Optional[str] = None) -> str:
        """
        Read content from a local file.
        Args:
            filename (str): Name of the file to read
            directory (Optional[str]): Directory to read file from. Uses target_directory if not provided
        Returns:
            str: The text content of the file
        """
        try:
            safe, file_path = self.check_escape(filename, directory)
            if not safe:
                return f"Error: Path '{filename}' is outside the allowed base directory"

            log_debug(f"Reading file from local system: {filename}")

            if not file_path.exists():
                return f"File not found: {file_path}"

            return file_path.read_text()

        except Exception as e:
            error_msg = f"Failed to read file: {str(e)}"
            log_error(error_msg)
            return f"Error: {error_msg}"
