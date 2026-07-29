import functools
import runpy
from pathlib import Path
from typing import Callable, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_exception, log_info, log_warning


@functools.lru_cache(maxsize=None)
def warn() -> None:
    log_warning("PythonTools can run arbitrary code, please provide human supervision.")


class PythonTools(Toolkit):
    """Toolkit for running Python code and managing files.

    Args:
        base_dir: Root directory for file operations. Defaults to cwd.
        safe_globals: Global scope for code execution.
        safe_locals: Local scope for code execution.
        restrict_to_base_dir: Restrict file operations to base_dir. Defaults to True.
        run_python_code: Enable run_python_code tool. Defaults to False (executes code).
        save_to_file_and_run: Enable save_to_file_and_run tool. Defaults to False (executes code).
        run_python_file_return_variable: Enable run_python_file_return_variable tool. Defaults to False (executes code).
        pip_install_package: Enable pip_install_package tool. Defaults to False (executes code).
        uv_pip_install_package: Enable uv_pip_install_package tool. Defaults to False (executes code).
        read_file: Enable read_file tool. Defaults to True.
        list_files: Enable list_files tool. Defaults to True.
        all: Enable all tools. Defaults to False.
    """

    def __init__(
        self,
        base_dir: Optional[Path] = None,
        safe_globals: Optional[dict] = None,
        safe_locals: Optional[dict] = None,
        restrict_to_base_dir: bool = True,
        run_python_code: bool = False,
        save_to_file_and_run: bool = False,
        run_python_file_return_variable: bool = False,
        pip_install_package: bool = False,
        uv_pip_install_package: bool = False,
        read_file: bool = True,
        list_files: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.base_dir: Path = (base_dir or Path.cwd()).resolve()
        self.restrict_to_base_dir = restrict_to_base_dir
        self.safe_globals: dict = safe_globals or globals()
        self.safe_locals: dict = safe_locals or locals()

        tools: List[Callable] = []
        if all or run_python_code:
            tools.append(self.run_python_code)
        if all or save_to_file_and_run:
            tools.append(self.save_to_file_and_run)
        if all or run_python_file_return_variable:
            tools.append(self.run_python_file_return_variable)
        if all or pip_install_package:
            tools.append(self.pip_install_package)
        if all or uv_pip_install_package:
            tools.append(self.uv_pip_install_package)
        if all or read_file:
            tools.append(self.read_file)
        if all or list_files:
            tools.append(self.list_files)

        super().__init__(name="python_tools", tools=tools, **kwargs)

    def save_to_file_and_run(
        self, file_name: str, code: str, variable_to_return: Optional[str] = None, overwrite: bool = True
    ) -> str:
        """This function saves Python code to a file called `file_name` and then runs it.
        If successful, returns the value of `variable_to_return` if provided otherwise returns a success message.
        If failed, returns an error message.

        Make sure the file_name ends with `.py`

        :param file_name: The name of the file the code will be saved to.
        :param code: The code to save and run.
        :param variable_to_return: The variable to return.
        :param overwrite: Overwrite the file if it already exists.
        :return: if run is successful, the value of `variable_to_return` if provided else file name.
        """
        try:
            warn()
            safe, file_path = self._check_path(file_name, self.base_dir, self.restrict_to_base_dir)
            if not safe:
                return f"Error: Path '{file_name}' is outside the allowed base directory"
            log_debug(f"Saving code to {file_path}")
            if not file_path.parent.exists():
                file_path.parent.mkdir(parents=True, exist_ok=True)
            if file_path.exists() and not overwrite:
                return f"File {file_name} already exists"
            file_path.write_text(code, encoding="utf-8")
            log_info(f"Saved: {file_path}")
            log_info(f"Running {file_path}")
            globals_after_run = runpy.run_path(str(file_path), init_globals=self.safe_globals, run_name="__main__")

            if variable_to_return:
                variable_value = globals_after_run.get(variable_to_return)
                if variable_value is None:
                    return f"Variable {variable_to_return} not found"
                log_debug(f"Variable {variable_to_return} value: {variable_value}")
                return str(variable_value)
            else:
                return f"successfully ran {str(file_path)}"
        except Exception as e:
            log_exception("Error saving and running code")
            return f"Error saving and running code: {e}"

    def run_python_file_return_variable(self, file_name: str, variable_to_return: Optional[str] = None) -> str:
        """This function runs code in a Python file.
        If successful, returns the value of `variable_to_return` if provided otherwise returns a success message.
        If failed, returns an error message.

        :param file_name: The name of the file to run.
        :param variable_to_return: The variable to return.
        :return: if run is successful, the value of `variable_to_return` if provided else file name.
        """
        try:
            warn()
            safe, file_path = self._check_path(file_name, self.base_dir, self.restrict_to_base_dir)
            if not safe:
                return f"Error: Path '{file_name}' is outside the allowed base directory"
            log_info(f"Running {file_path}")
            globals_after_run = runpy.run_path(str(file_path), init_globals=self.safe_globals, run_name="__main__")
            if variable_to_return:
                variable_value = globals_after_run.get(variable_to_return)
                if variable_value is None:
                    return f"Variable {variable_to_return} not found"
                log_debug(f"Variable {variable_to_return} value: {variable_value}")
                return str(variable_value)
            else:
                return f"successfully ran {str(file_path)}"
        except Exception as e:
            log_exception("Error running file")
            return f"Error running file: {e}"

    def read_file(self, file_name: str) -> str:
        """Reads the contents of the file `file_name` and returns the contents if successful.

        :param file_name: The name of the file to read.
        :return: The contents of the file if successful, otherwise returns an error message.
        """
        try:
            log_info(f"Reading file: {file_name}")
            safe, file_path = self._check_path(file_name, self.base_dir, self.restrict_to_base_dir)
            if not safe:
                log_error(f"Attempted to read file outside base directory: {file_name}")
                return "Error reading file: path outside allowed directory"
            contents = file_path.read_text(encoding="utf-8")
            return str(contents)
        except Exception as e:
            log_exception("Error reading file")
            return f"Error reading file: {e}"

    def list_files(self) -> str:
        """Returns a list of files in the base directory

        :return: Comma separated list of files in the base directory.
        """
        try:
            log_info(f"Reading files in : {self.base_dir}")
            files = [str(file_path.name) for file_path in self.base_dir.iterdir()]
            return ", ".join(files)
        except Exception as e:
            log_exception("Error reading files")
            return f"Error reading files: {e}"

    def run_python_code(self, code: str, variable_to_return: Optional[str] = None) -> str:
        """This function to runs Python code in the current environment.
        If successful, returns the value of `variable_to_return` if provided otherwise returns a success message.
        If failed, returns an error message.

        Returns the value of `variable_to_return` if successful, otherwise returns an error message.

        :param code: The code to run.
        :param variable_to_return: The variable to return.
        :return: value of `variable_to_return` if successful, otherwise returns an error message.
        """
        try:
            warn()

            log_debug(f"Running code:\n\n{code}\n\n")
            exec(code, self.safe_globals, self.safe_locals)

            if variable_to_return:
                variable_value = self.safe_locals.get(variable_to_return)
                if variable_value is None:
                    return f"Variable {variable_to_return} not found"
                log_debug(f"Variable {variable_to_return} value: {variable_value}")
                return str(variable_value)
            else:
                return "successfully ran python code"
        except Exception as e:
            log_exception("Error running python code")
            return f"Error running python code: {e}"

    def pip_install_package(self, package_name: str) -> str:
        """This function installs a package using pip in the current environment.
        If successful, returns a success message.
        If failed, returns an error message.

        :param package_name: The name of the package to install.
        :return: success message if successful, otherwise returns an error message.
        """
        try:
            warn()

            log_debug(f"Installing package {package_name}")
            import subprocess
            import sys

            subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
            return f"successfully installed package {package_name}"
        except Exception as e:
            log_exception(f"Error installing package {package_name}")
            return f"Error installing package {package_name}: {e}"

    def uv_pip_install_package(self, package_name: str) -> str:
        """This function installs a package using uv and pip in the current environment.
        If successful, returns a success message.
        If failed, returns an error message.

        :param package_name: The name of the package to install.
        :return: success message if successful, otherwise returns an error message.
        """
        try:
            warn()

            log_debug(f"Installing package {package_name}")
            import subprocess
            import sys

            subprocess.check_call([sys.executable, "-m", "uv", "pip", "install", package_name])
            return f"successfully installed package {package_name}"
        except Exception as e:
            log_exception(f"Error installing package {package_name}")
            return f"Error installing package {package_name}: {e}"
