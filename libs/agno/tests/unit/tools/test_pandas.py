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


def test_create_pandas_dataframe_rejects_read_pickle(pandas_tools, tmp_path):
    """Security regression: read_pickle (untrusted deserialization) must be rejected, never executed."""
    import os
    import pickle

    marker = tmp_path / "pwned"

    class _Evil:
        def __reduce__(self):
            return (os.system, (f"echo pwned > {marker}",))

    payload = tmp_path / "evil.pkl"
    payload.write_bytes(pickle.dumps(_Evil()))

    result = pandas_tools.create_pandas_dataframe(
        dataframe_name="x",
        create_using_function="read_pickle",
        function_parameters={"filepath_or_buffer": str(payload)},
    )
    assert "unsupported function" in result
    assert not marker.exists()  # deserialization payload must not run


def test_create_pandas_dataframe_allows_safe_reader(pandas_tools, tmp_path):
    csv = tmp_path / "data.csv"
    csv.write_text("a,b\n1,2\n")
    result = pandas_tools.create_pandas_dataframe(
        dataframe_name="csv_df",
        create_using_function="read_csv",
        function_parameters={"filepath_or_buffer": str(csv)},
    )
    assert result == "csv_df"


def test_run_dataframe_operation_blocks_dangerous_ops(pandas_tools):
    pandas_tools.create_pandas_dataframe(
        dataframe_name="df", create_using_function="DataFrame", function_parameters={"data": {"a": [1, 2]}}
    )
    for op in ("query", "eval", "to_pickle", "__class__"):
        result = pandas_tools.run_dataframe_operation(
            dataframe_name="df", operation=op, operation_parameters={}
        )
        assert "unsupported operation" in result
