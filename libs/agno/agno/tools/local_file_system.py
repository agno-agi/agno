import os
from pathlib import Path
from typing import Optional
from uuid import uuid4

from agno.tools import Toolkit
from agno.utils.log import logger


class LocalFileSystemTools(Toolkit):
    def __init__(
        self,
        target_directory: Optional[str] = None,
        default_extension: str = "txt",
    ):
        """
        Initialize the WriteToLocal toolkit.
        Args:
            target_directory (Optional[str]): Default directory to write files to. Creates if doesn't exist.
            default_extension (str): Default file extension to use if none specified.
        """
        super().__init__(name="write_to_local")

        self.target_directory = target_directory or os.getcwd()
        self.default_extension = default_extension.lstrip(".")

        target_path = Path(self.target_directory)
        target_path.mkdir(parents=True, exist_ok=True)

        self.register(self.write_file)

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
            directory = directory or self.target_directory
            if filename and "." in filename:
                filename, file_ext = os.path.splitext(filename)
                extension = extension or file_ext.lstrip(".")

            logger.debug(f"Writing file to local system: {filename}")

            extension = (extension or self.default_extension).lstrip(".")

            # Create directory if it doesn't exist
            dir_path = Path(directory)
            dir_path.mkdir(parents=True, exist_ok=True)

            # Construct full filename with extension
            full_filename = f"{filename}.{extension}"
            file_path = dir_path / full_filename

            file_path.write_text(content)

            return f"Successfully wrote file to: {file_path}"

        except Exception as e:
            error_msg = f"Failed to write file: {str(e)}"
            logger.error(error_msg)
            return f"Error: {error_msg}"

    def read_file(self, filename: str, directory: Optional[str] = None) -> str:
        """
        Read content from a local file.
        """
        file_path = Path(directory or self.target_directory) / filename
        if not file_path.exists():
            return f"File not found: {file_path}"
        return file_path.read_text()
