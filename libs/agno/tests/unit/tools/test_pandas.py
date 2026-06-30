import pandas as pd
import pytest

from agno.tools.pandas import PandasTools


@pytest.fixture
def pandas_tools():
    return PandasTools()


def test_pandas_tools_initialization():
    tools = PandasTools()
    assert len(tools.tools) == 2
    assert tools.name == "pandas_tools"
    assert isinstance(tools.dataframes, dict)
    assert len(tools.dataframes) == 0

    tools = PandasTools(enable_create_pandas_dataframe=False)
    assert len(tools.tools) == 1
    assert tools.name == "pandas_tools"

    tools = PandasTools(enable_run_dataframe_operation=False)
    assert len(tools.tools) == 1
    assert tools.name == "pandas_tools"

    tools = PandasTools(all=False, enable_create_pandas_dataframe=False, enable_run_dataframe_operation=False)
    assert len(tools.tools) == 0
    assert tools.name == "pandas_tools"


def test_create_pandas_dataframe(pandas_tools):
    data = {"col1": [1, 2, 3], "col2": ["a", "b", "c"]}
    result = pandas_tools.create_pandas_dataframe(
        dataframe_name="test_df", create_using_function="DataFrame", function_parameters={"data": data}
    )
    assert result == "test_df"
    assert "test_df" in pandas_tools.dataframes
    assert isinstance(pandas_tools.dataframes["test_df"], pd.DataFrame)

    result = pandas_tools.create_pandas_dataframe(
        dataframe_name="test_df", create_using_function="DataFrame", function_parameters={"data": data}
    )
    assert result == "Dataframe already exists: test_df"

    result = pandas_tools.create_pandas_dataframe(
        dataframe_name="empty_df", create_using_function="DataFrame", function_parameters={"data": {}}
    )
    assert result == "Dataframe is empty: empty_df"

    result = pandas_tools.create_pandas_dataframe(
        dataframe_name="invalid_df", create_using_function="invalid_function", function_parameters={}
    )
    assert "Error creating dataframe:" in result


def test_run_dataframe_operation(pandas_tools):
    data = {"col1": [1, 2, 3], "col2": ["a", "b", "c"]}
    pandas_tools.create_pandas_dataframe(
        dataframe_name="test_df", create_using_function="DataFrame", function_parameters={"data": data}
    )

    result = pandas_tools.run_dataframe_operation(
        dataframe_name="test_df", operation="head", operation_parameters={"n": 2}
    )
    assert isinstance(result, str)
    assert "1" in result and "2" in result
    assert "a" in result and "b" in result

    result = pandas_tools.run_dataframe_operation(
        dataframe_name="test_df", operation="describe", operation_parameters={}
    )
    assert isinstance(result, str)
    assert "count" in result
    assert "mean" in result

    result = pandas_tools.run_dataframe_operation(
        dataframe_name="test_df", operation="invalid_operation", operation_parameters={}
    )
    assert "Error running operation:" in result

    result = pandas_tools.run_dataframe_operation(
        dataframe_name="nonexistent_df", operation="head", operation_parameters={"n": 2}
    )
    assert "Error running operation:" in result
