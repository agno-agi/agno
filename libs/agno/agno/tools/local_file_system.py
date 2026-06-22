from pathlib import Path, PureWindowsPath
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
            if self._filename_has_path_components(filename):
                return f"Error: Path '{filename}' is outside the allowed target directory"

            if filename and "." in filename:
                path_obj = Path(filename)
                filename = path_obj.stem
                extension = extension or path_obj.suffix.lstrip(".")

            log_debug(f"Writing file to local system: {filename}")

            extension = (extension or self.default_extension).lstrip(".")

            target_path = Path(self.target_directory).resolve()
            dir_path = self._resolve_write_directory(directory, target_path)
            if dir_path is None:
                return f"Error: Directory '{directory}' is outside the allowed target directory"

            # Construct full filename with extension
            full_filename = f"{filename}.{extension}"
            file_path = (dir_path / full_filename).resolve()
            if not self._is_path_within_base(file_path, target_path):
                return f"Error: Path '{full_filename}' is outside the allowed target directory"

            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content)

            return f"Successfully wrote file to: {file_path}"

        except Exception as e:
            error_msg = f"Failed to write file: {str(e)}"
            log_error(error_msg)
            return f"Error: {error_msg}"

    def _resolve_write_directory(self, directory: Optional[str], target_path: Path) -> Optional[Path]:
        if not directory:
            return target_path

        requested_directory = Path(directory)
        if requested_directory.is_absolute():
            resolved_directory = requested_directory.resolve()
        else:
            safe, resolved_directory = self._check_path(directory, target_path)
            if not safe:
                return None

        if not self._is_path_within_base(resolved_directory, target_path):
            return None

        return resolved_directory

    @staticmethod
    def _filename_has_path_components(filename: str) -> bool:
        if filename in (".", ".."):
            return True

        native_path = Path(filename)
        windows_path = PureWindowsPath(filename)
        return (
            native_path.is_absolute()
            or windows_path.is_absolute()
            or len(native_path.parts) > 1
            or len(windows_path.parts) > 1
        )

    @staticmethod
    def _is_path_within_base(path: Path, base: Path) -> bool:
        try:
            path.relative_to(base)
        except ValueError:
            return False
        return True

    def read_file(self, filename: str, directory: Optional[str] = None) -> str:
        """
        Read content from a local file.
        """
        file_path = Path(directory or self.target_directory) / filename
        if not file_path.exists():
            return f"File not found: {file_path}"
        return file_path.read_text()
