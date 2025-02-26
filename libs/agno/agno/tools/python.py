import functools
import runpy
from pathlib import Path
from typing import Optional

from agno.tools import Toolkit
from agno.utils.log import logger


@functools.lru_cache(maxsize=None)
def warn() -> None:
    logger.warning("PythonTools can run arbitrary code, please provide human supervision.")


class PythonTools(Toolkit):
    def __init__(
        self,
        base_dir: Optional[Path] = None,
        save_and_run: bool = True,
        pip_install: bool = False,
        run_code: bool = False,
        list_files: bool = False,
        run_files: bool = False,
        read_files: bool = False,
        safe_globals: Optional[dict] = None,
        safe_locals: Optional[dict] = None,
    ):
        super().__init__(name="python_tools")

        self.base_dir: Path = base_dir or Path.cwd()

        # Restricted global and local scope
        self.safe_globals: dict = safe_globals or globals()
        self.safe_locals: dict = safe_locals or locals()

        if run_code:
            self.register(self.run_python_code, sanitize_arguments=False)
        if save_and_run:
            self.register(self.save_to_file_and_run, sanitize_arguments=False)
        if pip_install:
            self.register(self.pip_install_package)
        if run_files:
            self.register(self.run_python_file_return_variable)
        if read_files:
            self.register(self.read_file)
        if list_files:
            self.register(self.list_files)

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
            file_path = self.base_dir.joinpath(file_name)
            logger.debug(f"Saving code to {file_path}")
            if not file_path.parent.exists():
                file_path.parent.mkdir(parents=True, exist_ok=True)
            if file_path.exists() and not overwrite:
                return f"File {file_name} already exists"
            file_path.write_text(code, encoding="utf-8")
            logger.info(f"Saved: {file_path}")
            logger.info(f"Running {file_path}")
            globals_after_run = runpy.run_path(str(file_path), init_globals=self.safe_globals, run_name="__main__")

            if variable_to_return:
                variable_value = globals_after_run.get(variable_to_return)
                if variable_value is None:
                    return f"Variable {variable_to_return} not found"
                logger.debug(f"Variable {variable_to_return} value: {variable_value}")
                return str(variable_value)
            else:
                return f"successfully ran {str(file_path)}"
        except Exception as e:
            logger.error(f"Error saving and running code: {e}")
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
            file_path = self.base_dir.joinpath(file_name)

            logger.info(f"Running {file_path}")
            globals_after_run = runpy.run_path(str(file_path), init_globals=self.safe_globals, run_name="__main__")
            if variable_to_return:
                variable_value = globals_after_run.get(variable_to_return)
                if variable_value is None:
                    return f"Variable {variable_to_return} not found"
                logger.debug(f"Variable {variable_to_return} value: {variable_value}")
                return str(variable_value)
            else:
                return f"successfully ran {str(file_path)}"
        except Exception as e:
            logger.error(f"Error running file: {e}")
            return f"Error running file: {e}"

    def read_file(self, file_name: str) -> str:
        """Reads the contents of the file `file_name` and returns the contents if successful.

        :param file_name: The name of the file to read.
        :return: The contents of the file if successful, otherwise returns an error message.
        """
        try:
            logger.info(f"Reading file: {file_name}")
            file_path = self.base_dir.joinpath(file_name)
            contents = file_path.read_text(encoding="utf-8")
            return str(contents)
        except Exception as e:
            logger.error(f"Error reading file: {e}")
            return f"Error reading file: {e}"

    def list_files(self) -> str:
        """Returns a list of files in the base directory

        :return: Comma separated list of files in the base directory.
        """
        try:
            logger.info(f"Reading files in : {self.base_dir}")
            files = [str(file_path.name) for file_path in self.base_dir.iterdir()]
            return ", ".join(files)
        except Exception as e:
            logger.error(f"Error reading files: {e}")
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

            logger.debug(f"Running code:\n\n{code}\n\n")
            exec(code, self.safe_globals, self.safe_locals)

            if variable_to_return:
                variable_value = self.safe_locals.get(variable_to_return)
                if variable_value is None:
                    return f"Variable {variable_to_return} not found"
                logger.debug(f"Variable {variable_to_return} value: {variable_value}")
                return str(variable_value)
            else:
                return "successfully ran python code"
        except Exception as e:
            logger.error(f"Error running python code: {e}")
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

            logger.debug(f"Installing package {package_name}")
            import subprocess
            import sys

            subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
            return f"successfully installed package {package_name}"
        except Exception as e:
            logger.error(f"Error installing package {package_name}: {e}")
            return f"Error installing package {package_name}: {e}"
