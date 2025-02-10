import json
from pathlib import Path
from typing import Optional

from agno.tools import Toolkit
from agno.utils.log import logger


class FileTools(Toolkit):
    def __init__(
        self,
        base_dir: Optional[Path] = None,
        save_files: bool = True,
        read_files: bool = True,
        list_files: bool = True,
    ):
        super().__init__(name="file_tools")

        self.base_dir: Path = base_dir or Path.cwd()
        if save_files:
            self.register(self.save_file, sanitize_arguments=False)
        if read_files:
            self.register(self.read_file)
        if list_files:
            self.register(self.list_files)

    def save_file(self, contents: str, file_name: str, overwrite: bool = True) -> str:
        """Saves the contents to a file called `file_name` and returns the file name if successful.

        :param contents: The contents to save.
        :param file_name: The name of the file to save to.
        :param overwrite: Overwrite the file if it already exists.
        :return: The file name if successful, otherwise returns an error message.
        """
        try:
            file_path = self.base_dir.joinpath(file_name)
            logger.debug(f"Saving contents to {file_path}")
            if not file_path.parent.exists():
                file_path.parent.mkdir(parents=True, exist_ok=True)
            if file_path.exists() and not overwrite:
                return f"File {file_name} already exists"
            file_path.write_text(contents)
            logger.info(f"Saved: {file_path}")
            return str(file_name)
        except Exception as e:
            logger.error(f"Error saving to file: {e}")
            return f"Error saving to file: {e}"

    def read_file(self, file_name: str) -> str:
        """Reads the contents of the file `file_name` and returns the contents if successful.

        :param file_name: The name of the file to read.
        :return: The contents of the file if successful, otherwise returns an error message.
        """
        try:
            logger.info(f"Reading file: {file_name}")
            file_path = self.base_dir.joinpath(file_name)
            contents = file_path.read_text()
            return str(contents)
        except Exception as e:
            logger.error(f"Error reading file: {e}")
            return f"Error reading file: {e}"

    def list_files(self) -> str:
        """Returns a list of files in the base directory

        :return: The contents of the file if successful, otherwise returns an error message.
        """
        try:
            logger.info(f"Reading files in : {self.base_dir}")
            return json.dumps([str(file_path) for file_path in self.base_dir.iterdir()], indent=4)
        except Exception as e:
            logger.error(f"Error reading files: {e}")
            return f"Error reading files: {e}"
