import json
from pathlib import Path
from typing import Callable, List, Optional, Union

from agno.exceptions import PathSecurityError
from agno.tools import Toolkit
from agno.utils.log import log_debug, log_info, log_warning, logger
from agno.utils.path_safety import safe_join_relative_path


class AirflowTools(Toolkit):
    def __init__(
        self,
        dags_dir: Optional[Union[Path, str]] = None,
        save_dag_file: bool = False,
        read_dag_file: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """Toolkit for reading and writing Airflow DAG files.

        Quickstart: https://airflow.apache.org/docs/apache-airflow/stable/start.html

        Args:
            dags_dir: Directory containing DAG files. Defaults to the current working directory.
            save_dag_file: Enable the save_dag_file tool. Defaults to False (writes files to disk).
            read_dag_file: Enable the read_dag_file tool. Defaults to True.
            all: Enable all tools.
        """
        self.dags_dir = Path(dags_dir).resolve() if dags_dir is not None else Path.cwd().resolve()

        tools: List[Callable] = []
        if all or save_dag_file:
            tools.append(self.save_dag_file)
        if all or read_dag_file:
            tools.append(self.read_dag_file)

        super().__init__(name="airflow_tools", tools=tools, **kwargs)

    def save_dag_file(self, contents: str, dag_file: str) -> str:
        """Save Python code for an Airflow DAG to a file.

        Args:
            contents: The DAG Python code.
            dag_file: The filename to save to (relative to dags_dir).

        Returns:
            JSON with file_path on success or error on failure.
        """
        try:
            file_path = safe_join_relative_path(self.dags_dir, dag_file)
            log_debug(f"Saving contents to {file_path}")
            if not file_path.parent.exists():
                file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(contents)
            log_info(f"Saved: {file_path}")
            return json.dumps({"file_path": str(file_path)})
        except PathSecurityError as e:
            log_warning(f"Error saving to file: {str(e)}")
            return json.dumps({"error": f"Path security error: {e}"})
        except Exception as e:
            logger.exception("Error saving to file")
            return json.dumps({"error": f"Failed to save: {e}"})

    def read_dag_file(self, dag_file: str) -> str:
        """Read an Airflow DAG file and return its contents.

        Args:
            dag_file: The filename to read (relative to dags_dir).

        Returns:
            JSON with contents on success or error on failure.
        """
        try:
            log_info(f"Reading file: {dag_file}")
            file_path = safe_join_relative_path(self.dags_dir, dag_file)
            contents = file_path.read_text()
            return json.dumps({"contents": contents})
        except PathSecurityError as e:
            log_warning(f"Error reading file: {str(e)}")
            return json.dumps({"error": f"Path security error: {e}"})
        except Exception as e:
            logger.exception("Error reading file")
            return json.dumps({"error": f"Failed to read: {e}"})
