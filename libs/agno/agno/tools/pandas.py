from typing import Callable, Dict, List

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger

try:
    import pandas as pd
except ImportError:
    raise ImportError("`pandas` not installed. Please install using `pip install pandas`.")


class PandasTools(Toolkit):
    """Toolkit for creating and operating on pandas dataframes.

    Both tools dispatch to arbitrary pandas callables by name, which amounts to
    code execution. They are therefore opt-in: pass ``create_pandas_dataframe=True``,
    ``run_dataframe_operation=True``, or ``all=True`` to enable them.
    """

    def __init__(
        self,
        create_pandas_dataframe: bool = False,
        run_dataframe_operation: bool = False,
        all: bool = False,
        **kwargs,
    ):
        """Initialize Pandas toolkit for dataframe operations.

        Args:
            create_pandas_dataframe: Enable the create_pandas_dataframe tool.
                Defaults to False (dispatches to arbitrary pandas callables, i.e. code execution).
            run_dataframe_operation: Enable the run_dataframe_operation tool.
                Defaults to False (dispatches to arbitrary dataframe callables, i.e. code execution).
            all: Enable all tools.
        """
        self.dataframes: Dict[str, pd.DataFrame] = {}

        tools: List[Callable] = []
        if all or create_pandas_dataframe:
            tools.append(self.create_pandas_dataframe)
        if all or run_dataframe_operation:
            tools.append(self.run_dataframe_operation)

        super().__init__(name="pandas_tools", tools=tools, **kwargs)

    def create_pandas_dataframe(
        self, dataframe_name: str, create_using_function: str, function_parameters: Dict[str, object]
    ) -> str:
        """Create a pandas dataframe using a pandas function.

        Args:
            dataframe_name: Name to assign to the created dataframe.
            create_using_function: Pandas function to use (e.g., read_csv, read_json).
            function_parameters: Parameters to pass to the function.

        Returns:
            The dataframe name on success or error message.

        Example:
            create_pandas_dataframe("csv_data", "read_csv", {"filepath_or_buffer": "data.csv"})
        """
        try:
            log_debug(f"Creating dataframe: {dataframe_name}")
            log_debug(f"Using function: {create_using_function}")
            log_debug(f"With parameters: {function_parameters}")

            if dataframe_name in self.dataframes:
                return f"Dataframe already exists: {dataframe_name}"

            # Create the dataframe
            dataframe = getattr(pd, create_using_function)(**function_parameters)
            if dataframe is None:
                return f"Error creating dataframe: {dataframe_name}"
            if not isinstance(dataframe, pd.DataFrame):
                return f"Error creating dataframe: {dataframe_name}"
            if dataframe.empty:
                return f"Dataframe is empty: {dataframe_name}"
            self.dataframes[dataframe_name] = dataframe
            log_debug(f"Created dataframe: {dataframe_name}")
            return dataframe_name
        except Exception as e:
            logger.exception("Error creating dataframe")
            return f"Error creating dataframe: {e}"

    def run_dataframe_operation(
        self, dataframe_name: str, operation: str, operation_parameters: Dict[str, object]
    ) -> str:
        """Run an operation on a dataframe.

        Args:
            dataframe_name: Name of the dataframe to operate on.
            operation: Operation to run (e.g., head, tail, describe).
            operation_parameters: Parameters to pass to the operation.

        Returns:
            The result of the operation or error message.

        Example:
            run_dataframe_operation("csv_data", "head", {"n": 5})
        """
        try:
            log_debug(f"Running operation: {operation}")
            log_debug(f"On dataframe: {dataframe_name}")
            log_debug(f"With parameters: {operation_parameters}")

            # Get the dataframe
            dataframe = self.dataframes.get(dataframe_name)

            # Run the operation
            result = getattr(dataframe, operation)(**operation_parameters)

            log_debug(f"Ran operation: {operation}")
            try:
                try:
                    return result.to_string()
                except AttributeError:
                    return str(result)
            except Exception:
                return "Operation ran successfully"
        except Exception as e:
            logger.exception("Error running operation")
            return f"Error running operation: {e}"
