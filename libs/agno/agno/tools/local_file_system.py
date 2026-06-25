from pathlib import Path
from typing import Optional
from uuid import uuid4

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error


class LocalFileSystemTools(Toolkit):
    def __init__(
        self,
        target_directory: Optional[str] = None,
        default_extension: str = "txt",
        enable_write_file: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """
        Initialize the WriteToLocal toolkit.
        Args:
            target_directory (Optional[str]): Default directory to write files to. Creates if doesn't exist.
            default_extension (str): Default file extension to use if none specified.
        """

        self.target_directory = target_directory or str(Path.cwd())
        self.default_extension = default_extension.lstrip(".")

        target_path = Path(self.target_directory)
        target_path.mkdir(parents=True, exist_ok=True)

        tools = []
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
            directory = directory or "."
            base_directory = Path(self.target_directory)
            filename_path = Path(filename)
            filename_parent = filename_path.parent
            filename_base = filename_path.with_suffix("").name
            extension = extension or filename_path.suffix.lstrip(".")

            log_debug(f"Writing file to local system: {filename}")

            extension = (extension or self.default_extension).lstrip(".")

            safe_directory, dir_path = self._check_path(directory, base_directory)
            if not safe_directory:
                return "Error: directory escapes target directory"

            # Keep directory constraints while still supporting paths inside filename.
            if str(filename_parent) not in ("", "."):
                safe_file_dir, checked_file_dir = self._check_path(str(filename_parent), dir_path)
                if not safe_file_dir:
                    return "Error: file path escapes target directory"
                dir_path = checked_file_dir

            safe_file, file_path = self._check_path(f"{filename_base}.{extension}", dir_path)
            if not safe_file:
                return "Error: file path escapes target directory"

            dir_path.mkdir(parents=True, exist_ok=True)
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
        """
        file_path = Path(directory or self.target_directory) / filename
        if not file_path.exists():
            return f"File not found: {file_path}"
        return file_path.read_text()
