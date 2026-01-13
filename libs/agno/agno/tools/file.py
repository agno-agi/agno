import json
from pathlib import Path
from typing import Any, List, Optional, Tuple

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error


class FileTools(Toolkit):
    def __init__(
        self,
        base_dir: Optional[Path] = None,
        enable_save_file: bool = True,
        enable_read_file: bool = True,
        enable_delete_file: bool = False,
        enable_list_files: bool = True,
        enable_search_files: bool = True,
        enable_read_file_chunk: bool = True,
        enable_replace_file_chunk: bool = True,
        expose_base_directory: bool = False,
        max_file_length: int = 10000000,
        max_file_lines: int = 100000,
        line_separator: str = "\n",
        all: bool = False,
        **kwargs,
    ):
        self.base_dir: Path = (base_dir or Path.cwd()).resolve()

        tools: List[Any] = []
        self.max_file_length = max_file_length
        self.max_file_lines = max_file_lines
        self.line_separator = line_separator
        self.expose_base_directory = expose_base_directory
        if all or enable_save_file:
            tools.append(self.save_file)
        if all or enable_read_file:
            tools.append(self.read_file)
        if all or enable_list_files:
            tools.append(self.list_files)
        if all or enable_search_files:
            tools.append(self.search_files)
        if all or enable_delete_file:
            tools.append(self.delete_file)
        if all or enable_read_file_chunk:
            tools.append(self.read_file_chunk)
        if all or enable_replace_file_chunk:
            tools.append(self.replace_file_chunk)

        super().__init__(name="file_tools", tools=tools, **kwargs)

    def check_escape(self, relative_path: str) -> Tuple[bool, Path]:
        """Check if the file path is within the base directory.

        Alias for _check_path maintained for backward compatibility.

        Args:
            relative_path: The file name or relative path to check.

        Returns:
            Tuple of (is_safe, resolved_path). If not safe, returns base_dir as the path.
        """
        return self._check_path(relative_path, self.base_dir)

    def save_file(self, contents: str, file_name: str, overwrite: bool = True, encoding: str = "utf-8") -> str:
        """Saves the contents to a file called `file_name` and returns the file name if successful.

        :param contents: The contents to save.
        :param file_name: The name of the file to save to.
        :param overwrite: Overwrite the file if it already exists.
        :return: The file name if successful, otherwise returns an error message.
        """
        try:
            safe, file_path = self.check_escape(file_name)
            if not (safe):
                log_error(f"Attempted to save file: {file_name}")
                return "Error saving file"
            log_debug(f"Saving contents to {file_path}")
            if not file_path.parent.exists():
                file_path.parent.mkdir(parents=True, exist_ok=True)
            if file_path.exists() and not overwrite:
                return f"File {file_name} already exists"
            file_path.write_text(contents, encoding=encoding)
            log_debug(f"Saved: {file_path}")
            return str(file_name)
        except Exception as e:
            log_error(f"Error saving to file: {e}")
            return f"Error saving to file: {e}"

    def read_file_chunk(self, file_name: str, start_line: int, end_line: int, encoding: str = "utf-8") -> str:
        """Reads the contents of the file `file_name` and returns lines from start_line to end_line.

        :param file_name: The name of the file to read.
        :param start_line: Number of first line in the returned chunk
        :param end_line: Number of the last line in the returned chunk
        :param encoding: Encoding to use, default - utf-8

        :return: The contents of the selected chunk
        """
        try:
            log_debug(f"Reading file: {file_name}")
            safe, file_path = self.check_escape(file_name)
            if not (safe):
                log_error(f"Attempted to read file: {file_name}")
                return "Error reading file"
            contents = file_path.read_text(encoding=encoding)
            lines = contents.split(self.line_separator)
            return self.line_separator.join(lines[start_line : end_line + 1])
        except Exception as e:
            log_error(f"Error reading file: {e}")
            return f"Error reading file: {e}"

    def replace_file_chunk(
        self, file_name: str, start_line: int, end_line: int, chunk: str, encoding: str = "utf-8"
    ) -> str:
        """Reads the contents of the file, replaces lines
        between start_line and end_line with chunk and writes the file

        :param file_name: The name of the file to process.
        :param start_line: Number of first line in the replaced chunk
        :param end_line: Number of the last line in the replaced chunk
        :param chunk: String to be inserted instead of lines from start_line to end_line. Can have multiple lines.
        :param encoding: Encoding to use, default - utf-8

        :return: file name if successfull, error message otherwise
        """
        try:
            log_debug(f"Patching file: {file_name}")
            safe, file_path = self.check_escape(file_name)
            if not (safe):
                log_error(f"Attempted to read file: {file_name}")
                return "Error reading file"
            contents = file_path.read_text(encoding=encoding)
            lines = contents.split(self.line_separator)
            start = lines[0:start_line]
            end = lines[end_line + 1 :]
            return self.save_file(
                file_name=file_name, contents=self.line_separator.join(start + [chunk] + end), encoding=encoding
            )
        except Exception as e:
            log_error(f"Error patching file: {e}")
            return f"Error patching file: {e}"

    def read_file(self, file_name: str, encoding: str = "utf-8") -> str:
        """Reads the contents of the file `file_name` and returns the contents if successful.

        :param file_name: The name of the file to read.
        :param encoding: Encoding to use, default - utf-8
        :return: The contents of the file if successful, otherwise returns an error message.
        """
        try:
            log_debug(f"Reading file: {file_name}")
            safe, file_path = self.check_escape(file_name)
            if not (safe):
                log_error(f"Attempted to read file: {file_name}")
                return "Error reading file"
            contents = file_path.read_text(encoding=encoding)
            if len(contents) > self.max_file_length:
                return "Error reading file: file too long. Use read_file_chunk instead"
            if len(contents.split(self.line_separator)) > self.max_file_lines:
                return "Error reading file: file too long. Use read_file_chunk instead"

            return str(contents)
        except Exception as e:
            log_error(f"Error reading file: {e}")
            return f"Error reading file: {e}"

    def delete_file(self, file_name: str) -> str:
        """Deletes a file
        :param file_name: Name of the file to delete

        :return: Empty string, if operation succeeded, otherwise returns an error message
        """
        safe, path = self.check_escape(file_name)
        try:
            if safe:
                if path.is_dir():
                    path.rmdir()
                    return ""
                path.unlink()
                return ""
            else:
                log_error(f"Attempt to delete file outside {self.base_dir}: {file_name}")
                return "Incorrect file_name"
        except Exception as e:
            log_error(f"Error removing {file_name}: {e}")
            return f"Error removing file: {e}"

    def list_files(self, **kwargs) -> str:
        """Returns a list of files in directory
        :param directory: (Optional) name of directory to list.

        :return: The contents of the file if successful, otherwise returns an error message.
        """
        directory = kwargs.get("directory", ".")
        try:
            log_debug(f"Reading files in : {self.base_dir}/{directory}")
            safe, d = self.check_escape(directory)
            if safe:
                return json.dumps([str(file_path.relative_to(self.base_dir)) for file_path in d.iterdir()], indent=4)
            else:
                return "{}"
        except Exception as e:
            log_error(f"Error reading files: {e}")
            return f"Error reading files: {e}"

    def search_files(self, pattern: str) -> str:
        """Searches for files in the base directory that match the pattern

        :param pattern: The pattern to search for, e.g. "*.txt", "file*.csv", "**/*.py".
        :return: JSON formatted list of matching file paths, or error message.
        """
        try:
            if not pattern or not pattern.strip():
                return "Error: Pattern cannot be empty"

            log_debug(f"Searching files in {self.base_dir} with pattern {pattern}")
            matching_files = list(self.base_dir.glob(pattern))
            result = None
            if self.expose_base_directory:
                file_paths = [str(file_path) for file_path in matching_files]
                result = {
                    "pattern": pattern,
                    "matches_found": len(file_paths),
                    "base_directory": str(self.base_dir),
                    "files": file_paths,
                }
            else:
                file_paths = [str(file_path.relative_to(self.base_dir)) for file_path in matching_files]

                result = {
                    "pattern": pattern,
                    "matches_found": len(file_paths),
                    "files": file_paths,
                }
            log_debug(f"Found {len(file_paths)} files matching pattern {pattern}")
            return json.dumps(result, indent=2)

        except Exception as e:
            error_msg = f"Error searching files with pattern '{pattern}': {e}"
            log_error(error_msg)
            return error_msg
