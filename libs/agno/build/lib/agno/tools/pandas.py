from typing import Any, Dict

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger

try:
    import pandas as pd
except ImportError:
    raise ImportError("`pandas` not installed. Please install using `pip install pandas`.")


class PandasTools(Toolkit):
    def __init__(self, **kwargs):
        super().__init__(name="pandas_tools", **kwargs)

        self.dataframes: Dict[str, pd.DataFrame] = {}
        self.register(self.create_pandas_dataframe)
        self.register(self.run_dataframe_operation)

    def create_pandas_dataframe(
        self, dataframe_name: str, create_using_function: str, function_parameters: Dict[str, Any]
    ) -> str:
        """Creates a pandas dataframe named `dataframe_name` by running a function `create_using_function` with the parameters `function_parameters`.
        Returns the created dataframe name as a string if successful, otherwise returns an error message.

        For Example:
        - To create a dataframe `csv_data` by reading a CSV file, use: {"dataframe_name": "csv_data", "create_using_function": "read_csv", "function_parameters": {"filepath_or_buffer": "data.csv"}}
        - To create a dataframe `csv_data` by reading a JSON file, use: {"dataframe_name": "json_data", "create_using_function": "read_json", "function_parameters": {"path_or_buf": "data.json"}}

        :param dataframe_name: The name of the dataframe to create.
        :param create_using_function: The function to use to create the dataframe.
        :param function_parameters: The parameters to pass to the function.
        :return: The name of the created dataframe if successful, otherwise an error message.
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
            logger.error(f"Error creating dataframe: {e}")
            return f"Error creating dataframe: {e}"

    def run_dataframe_operation(self, dataframe_name: str, operation: str, operation_parameters: Dict[str, Any]) -> str:
        """Runs an operation `operation` on a dataframe `dataframe_name` with the parameters `operation_parameters`.
        Returns the result of the operation as a string if successful, otherwise returns an error message.

        For Example:
        - To get the first 5 rows of a dataframe `csv_data`, use: {"dataframe_name": "csv_data", "operation": "head", "operation_parameters": {"n": 5}}
        - To get the last 5 rows of a dataframe `csv_data`, use: {"dataframe_name": "csv_data", "operation": "tail", "operation_parameters": {"n": 5}}

        :param dataframe_name: The name of the dataframe to run the operation on.
        :param operation: The operation to run on the dataframe.
        :param operation_parameters: The parameters to pass to the operation.
        :return: The result of the operation if successful, otherwise an error message.
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
            logger.error(f"Error running operation: {e}")
            return f"Error running operation: {e}"
