"""Unit tests for VisualizationTools class."""

import json
import os
import tempfile
from unittest.mock import patch

import pytest

from agno.tools.visualization import VisualizationTools


@pytest.fixture
def temp_output_dir():
    """Create a temporary directory for test outputs."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield temp_dir


@pytest.fixture
def viz_tools(temp_output_dir):
    """Create a VisualizationTools instance with all chart types enabled."""
    return VisualizationTools(output_dir=temp_output_dir)


@pytest.fixture
def basic_viz_tools(temp_output_dir):
    """Create a VisualizationTools instance with only basic chart types."""
    return VisualizationTools(output_dir=temp_output_dir)


def test_initialization_with_selective_charts(temp_output_dir):
    """Test initialization with only selected chart types."""
    tools = VisualizationTools(
        output_dir=temp_output_dir,
        enable_create_bar_chart=True,
        enable_create_line_chart=True,
        enable_create_pie_chart=False,
        enable_create_scatter_plot=False,
        enable_create_histogram=True,
    )

    function_names = [func.name for func in tools.functions.values()]

    assert "create_bar_chart" in function_names
    assert "create_line_chart" in function_names
    assert "create_pie_chart" not in function_names
    assert "create_scatter_plot" not in function_names
    assert "create_histogram" in function_names


def test_initialization_with_all_charts(viz_tools):
    """Test initialization with all chart types enabled."""
    function_names = [func.name for func in viz_tools.functions.values()]

    assert "create_bar_chart" in function_names
    assert "create_line_chart" in function_names
    assert "create_pie_chart" in function_names
    assert "create_scatter_plot" in function_names
    assert "create_histogram" in function_names


def test_output_directory_creation(temp_output_dir):
    """Test that output directory is created if it doesn't exist."""
    non_existent_dir = os.path.join(temp_output_dir, "charts")
    assert not os.path.exists(non_existent_dir)

    VisualizationTools(output_dir=non_existent_dir)

    assert os.path.exists(non_existent_dir)


@patch("matplotlib.pyplot.savefig")
@patch("matplotlib.pyplot.close")
@patch("matplotlib.pyplot.figure")
@patch("matplotlib.pyplot.bar")
@patch("matplotlib.pyplot.title")
@patch("matplotlib.pyplot.xlabel")
@patch("matplotlib.pyplot.ylabel")
@patch("matplotlib.pyplot.xticks")
@patch("matplotlib.pyplot.tight_layout")
def test_create_bar_chart_success(
    mock_tight_layout,
    mock_xticks,
    mock_ylabel,
    mock_xlabel,
    mock_title,
    mock_bar,
    mock_figure,
    mock_close,
    mock_savefig,
    viz_tools,
):
    """Test successful bar chart creation."""
    test_data = {"A": 10, "B": 20, "C": 15}

    result = viz_tools.create_bar_chart(data=test_data, title="Test Chart", x_label="Categories", y_label="Values")

    result_dict = json.loads(result)

    assert result_dict["status"] == "success"
    assert result_dict["chart_type"] == "bar_chart"
    assert result_dict["title"] == "Test Chart"
    assert result_dict["data_points"] == 3
    assert "file_path" in result_dict

    # Verify matplotlib functions were called
    assert mock_figure.call_count >= 1  # May be called multiple times for figure and grid
    mock_bar.assert_called_once()
    assert mock_title.called  # Title is called with fontsize and fontweight params
    assert "Test Chart" in str(mock_title.call_args)
    assert mock_xlabel.called  # Labels are called with fontsize params
    assert "Categories" in str(mock_xlabel.call_args)
    assert mock_ylabel.called
    assert "Values" in str(mock_ylabel.call_args)
    mock_savefig.assert_called_once()
    mock_close.assert_called_once()


@patch("matplotlib.pyplot.savefig")
@patch("matplotlib.pyplot.close")
@patch("matplotlib.pyplot.figure")
@patch("matplotlib.pyplot.bar")
@patch("matplotlib.pyplot.title")
@patch("matplotlib.pyplot.xlabel")
@patch("matplotlib.pyplot.ylabel")
@patch("matplotlib.pyplot.xticks")
@patch("matplotlib.pyplot.tight_layout")
def test_create_bar_chart_with_list_of_dicts(
    mock_tight_layout,
    mock_xticks,
    mock_ylabel,
    mock_xlabel,
    mock_title,
    mock_bar,
    mock_figure,
    mock_close,
    mock_savefig,
    viz_tools,
):
    """Test bar chart creation with list of dictionaries data."""
    test_data = [
        {"Month": "January", "Sales": 10000},
        {"Month": "February", "Sales": 15000},
        {"Month": "March", "Sales": 12000},
    ]

    result = viz_tools.create_bar_chart(data=test_data, title="Sales Chart", x_label="Month", y_label="Sales")

    result_dict = json.loads(result)

    assert result_dict["status"] == "success"
    assert result_dict["chart_type"] == "bar_chart"
    assert result_dict["title"] == "Sales Chart"
    assert result_dict["data_points"] == 3
    assert "file_path" in result_dict

    # Verify matplotlib functions were called
    assert mock_figure.call_count >= 1  # May be called multiple times for figure and grid
    mock_bar.assert_called_once()
    assert mock_title.called  # Title is called with fontsize and fontweight params
    assert "Sales Chart" in str(mock_title.call_args)


@patch("matplotlib.pyplot.savefig")
@patch("matplotlib.pyplot.close")
@patch("matplotlib.pyplot.figure")
@patch("matplotlib.pyplot.plot")
@patch("matplotlib.pyplot.title")
@patch("matplotlib.pyplot.xlabel")
@patch("matplotlib.pyplot.ylabel")
@patch("matplotlib.pyplot.xticks")
@patch("matplotlib.pyplot.grid")
@patch("matplotlib.pyplot.tight_layout")
def test_create_line_chart_success(
    mock_tight_layout,
    mock_grid,
    mock_xticks,
    mock_ylabel,
    mock_xlabel,
    mock_title,
    mock_plot,
    mock_figure,
    mock_close,
    mock_savefig,
    viz_tools,
):
    """Test successful line chart creation."""
    test_data = {"Jan": 100, "Feb": 150, "Mar": 120}

    result = viz_tools.create_line_chart(data=test_data, title="Monthly Trend", x_label="Month", y_label="Sales")

    result_dict = json.loads(result)

    assert result_dict["status"] == "success"
    assert result_dict["chart_type"] == "line_chart"
    assert result_dict["title"] == "Monthly Trend"
    assert result_dict["data_points"] == 3

    # Verify matplotlib functions were called
    mock_figure.assert_called_once_with(figsize=(10, 6))
    mock_plot.assert_called_once()
    mock_grid.assert_called_once_with(True, alpha=0.3)


@patch("matplotlib.pyplot.savefig")
@patch("matplotlib.pyplot.close")
@patch("matplotlib.pyplot.figure")
@patch("matplotlib.pyplot.pie")
@patch("matplotlib.pyplot.title")
@patch("matplotlib.pyplot.axis")
def test_create_pie_chart_success(
    mock_axis,
    mock_title,
    mock_pie,
    mock_figure,
    mock_close,
    mock_savefig,
    viz_tools,
):
    """Test successful pie chart creation."""
    test_data = {"Red": 30, "Blue": 25, "Green": 20, "Yellow": 25}

    result = viz_tools.create_pie_chart(data=test_data, title="Color Distribution")

    result_dict = json.loads(result)

    assert result_dict["status"] == "success"
    assert result_dict["chart_type"] == "pie_chart"
    assert result_dict["title"] == "Color Distribution"
    assert result_dict["data_points"] == 4

    # Verify matplotlib functions were called
    mock_figure.assert_called_once_with(figsize=(10, 8))
    mock_pie.assert_called_once()
    mock_title.assert_called_once_with("Color Distribution")
    mock_axis.assert_called_once_with("equal")


@patch("matplotlib.pyplot.savefig")
@patch("matplotlib.pyplot.close")
@patch("matplotlib.pyplot.figure")
@patch("matplotlib.pyplot.scatter")
@patch("matplotlib.pyplot.title")
@patch("matplotlib.pyplot.xlabel")
@patch("matplotlib.pyplot.ylabel")
@patch("matplotlib.pyplot.grid")
@patch("matplotlib.pyplot.tight_layout")
def test_create_scatter_plot_success(
    mock_tight_layout,
    mock_grid,
    mock_ylabel,
    mock_xlabel,
    mock_title,
    mock_scatter,
    mock_figure,
    mock_close,
    mock_savefig,
    viz_tools,
):
    """Test successful scatter plot creation."""
    x_data = [1, 2, 3, 4, 5]
    y_data = [2, 4, 6, 8, 10]

    result = viz_tools.create_scatter_plot(
        x_data=x_data, y_data=y_data, title="Correlation Analysis", x_label="X Values", y_label="Y Values"
    )

    result_dict = json.loads(result)

    assert result_dict["status"] == "success"
    assert result_dict["chart_type"] == "scatter_plot"
    assert result_dict["title"] == "Correlation Analysis"
    assert result_dict["data_points"] == 5

    # Verify matplotlib functions were called
    mock_figure.assert_called_once_with(figsize=(10, 6))
    mock_scatter.assert_called_once()
    mock_grid.assert_called_once_with(True, alpha=0.3)


def test_scatter_plot_missing_data(viz_tools):
    """Test scatter plot with missing data parameters."""
    result = viz_tools.create_scatter_plot(title="Missing Data Test")

    result_dict = json.loads(result)
    assert result_dict["status"] == "error"
    assert "Missing x_data and y_data" in result_dict["error"]


def test_scatter_plot_mismatched_data_length(viz_tools):
    """Test scatter plot with mismatched data lengths."""
    x_data = [1, 2, 3]
    y_data = [1, 2]  # Different length

    result = viz_tools.create_scatter_plot(x_data=x_data, y_data=y_data)

    result_dict = json.loads(result)
    assert result_dict["status"] == "error"
    assert "same length" in result_dict["error"]


@patch("matplotlib.pyplot.savefig")
@patch("matplotlib.pyplot.close")
@patch("matplotlib.pyplot.figure")
@patch("matplotlib.pyplot.scatter")
@patch("matplotlib.pyplot.title")
@patch("matplotlib.pyplot.xlabel")
@patch("matplotlib.pyplot.ylabel")
@patch("matplotlib.pyplot.grid")
@patch("matplotlib.pyplot.tight_layout")
def test_create_scatter_plot_with_alternative_params(
    mock_tight_layout,
    mock_grid,
    mock_ylabel,
    mock_xlabel,
    mock_title,
    mock_scatter,
    mock_figure,
    mock_close,
    mock_savefig,
    viz_tools,
):
    """Test scatter plot creation with alternative x,y parameters."""
    x_vals = [1, 2, 3, 4, 5]
    y_vals = [2, 4, 6, 8, 10]

    result = viz_tools.create_scatter_plot(x=x_vals, y=y_vals, title="Alt Params Test")

    result_dict = json.loads(result)

    assert result_dict["status"] == "success"
    assert result_dict["chart_type"] == "scatter_plot"
    assert result_dict["data_points"] == 5


@patch("matplotlib.pyplot.savefig")
@patch("matplotlib.pyplot.close")
@patch("matplotlib.pyplot.figure")
@patch("matplotlib.pyplot.hist")
@patch("matplotlib.pyplot.title")
@patch("matplotlib.pyplot.xlabel")
@patch("matplotlib.pyplot.ylabel")
@patch("matplotlib.pyplot.grid")
@patch("matplotlib.pyplot.tight_layout")
def test_create_histogram_success(
    mock_tight_layout,
    mock_grid,
    mock_ylabel,
    mock_xlabel,
    mock_title,
    mock_hist,
    mock_figure,
    mock_close,
    mock_savefig,
    viz_tools,
):
    """Test successful histogram creation."""
    test_data = [1, 2, 2, 3, 3, 3, 4, 4, 5]

    result = viz_tools.create_histogram(
        data=test_data, bins=5, title="Distribution Analysis", x_label="Values", y_label="Frequency"
    )

    result_dict = json.loads(result)

    assert result_dict["status"] == "success"
    assert result_dict["chart_type"] == "histogram"
    assert result_dict["title"] == "Distribution Analysis"
    assert result_dict["data_points"] == 9
    assert result_dict["bins"] == 5

    # Verify matplotlib functions were called
    mock_figure.assert_called_once_with(figsize=(10, 6))
    mock_hist.assert_called_once()
    mock_grid.assert_called_once_with(True, alpha=0.3)


def test_histogram_with_mixed_data_types(viz_tools):
    """Test histogram creation with mixed data types."""
    test_data = [1, 2.5, "3", 4, "invalid", 5.0]

    result = viz_tools.create_histogram(test_data, title="Mixed Data Test")

    result_dict = json.loads(result)
    assert result_dict["status"] == "success"
    assert result_dict["data_points"] == 5  # Should filter out invalid values


def test_histogram_with_empty_data(viz_tools):
    """Test histogram with empty data."""
    result = viz_tools.create_histogram([])

    result_dict = json.loads(result)
    assert result_dict["status"] == "error"
    assert "non-empty list" in result_dict["error"]


def test_histogram_with_no_valid_numeric_data(viz_tools):
    """Test histogram with no valid numeric data."""
    result = viz_tools.create_histogram(["invalid", "data", "only"])

    result_dict = json.loads(result)
    assert result_dict["status"] == "error"
    assert "No valid numeric data" in result_dict["error"]


def test_custom_filename(viz_tools):
    """Test chart creation with custom filename."""
    test_data = {"A": 10, "B": 20}
    custom_filename = "custom_chart.png"

    with patch("matplotlib.pyplot.savefig"):
        result = viz_tools.create_bar_chart(data=test_data, filename=custom_filename)

        result_dict = json.loads(result)
        assert result_dict["status"] == "success"
        assert custom_filename in result_dict["file_path"]


@patch("matplotlib.pyplot.savefig", side_effect=Exception("Save failed"))
def test_error_handling(mock_savefig, viz_tools):
    """Test error handling in chart creation."""
    test_data = {"A": 10, "B": 20}

    result = viz_tools.create_bar_chart(data=test_data)

    result_dict = json.loads(result)
    assert result_dict["status"] == "error"
    assert "Save failed" in result_dict["error"]


def test_matplotlib_import_error():
    """Test handling of matplotlib import error."""
    with patch.dict("sys.modules", {"matplotlib": None}):
        with pytest.raises(ImportError, match="matplotlib is not installed"):
            VisualizationTools()


def test_basic_initialization_has_correct_functions(basic_viz_tools):
    """Test that basic initialization includes default chart types."""
    function_names = [func.name for func in basic_viz_tools.functions.values()]

    assert "create_bar_chart" in function_names
    assert "create_line_chart" in function_names
    assert "create_pie_chart" in function_names
    assert "create_scatter_plot" in function_names
    assert "create_histogram" in function_names


def test_normalize_data_for_charts_dict(viz_tools):
    """Test data normalization with dictionary input."""
    data = {"A": 10, "B": 20.5, "C": "invalid"}
    normalized = viz_tools._normalize_data_for_charts(data)

    expected = {"A": 10.0, "B": 20.5, "C": 0.0}
    assert normalized == expected


def test_normalize_data_for_charts_list_of_dicts(viz_tools):
    """Test data normalization with list of dictionaries."""
    data = [{"month": "Jan", "sales": 1000}, {"month": "Feb", "sales": 1500}, {"month": "Mar", "sales": 1200}]
    normalized = viz_tools._normalize_data_for_charts(data)

    expected = {"Jan": 1000.0, "Feb": 1500.0, "Mar": 1200.0}
    assert normalized == expected


def test_normalize_data_for_charts_list_of_values(viz_tools):
    """Test data normalization with list of values."""
    data = [10, 20, 30]
    normalized = viz_tools._normalize_data_for_charts(data)

    expected = {"Item 1": 10.0, "Item 2": 20.0, "Item 3": 30.0}
    assert normalized == expected


def test_create_bar_chart_with_json_string(viz_tools):
    """Test bar chart creation with JSON string data."""
    data = '{"A": 10, "B": 20, "C": 15}'

    with patch("matplotlib.pyplot.savefig"):
        result = viz_tools.create_bar_chart(data, title="JSON Chart")

        result_dict = json.loads(result)
        assert result_dict["status"] == "success"
        assert result_dict["chart_type"] == "bar_chart"
        assert result_dict["data_points"] == 3


# Tests for new enhancements


def test_create_bar_chart_with_colors(viz_tools):
    """Test bar chart with custom colors."""
    data = {"Red": 10, "Green": 20, "Blue": 30}
    colors = ["red", "green", "blue"]

    with patch("matplotlib.pyplot.savefig"):
        result = viz_tools.create_bar_chart(data, colors=colors, title="Colored Bars")

        result_dict = json.loads(result)
        assert result_dict["status"] == "success"


def test_create_bar_chart_with_show_values(viz_tools):
    """Test bar chart with value labels."""
    data = {"A": 100, "B": 200, "C": 300}

    with patch("matplotlib.pyplot.savefig"):
        result = viz_tools.create_bar_chart(data, show_values=True, title="Bars with Values")

        result_dict = json.loads(result)
        assert result_dict["status"] == "success"


def test_create_bar_chart_with_annotations(viz_tools):
    """Test bar chart with annotations."""
    data = {"A": 10, "B": 20, "C": 30}
    annotations = [{"x": 1, "y": 20, "text": "Peak value"}]

    with patch("matplotlib.pyplot.savefig"):
        result = viz_tools.create_bar_chart(data, annotations=annotations, title="Annotated Chart")

        result_dict = json.loads(result)
        assert result_dict["status"] == "success"


def test_create_line_chart_with_colors(viz_tools):
    """Test line chart with custom color."""
    data = {"Jan": 10, "Feb": 20, "Mar": 30, "Apr": 25}

    with patch("matplotlib.pyplot.savefig"):
        result = viz_tools.create_line_chart(data, colors=["purple"], title="Purple Line")

        result_dict = json.loads(result)
        assert result_dict["status"] == "success"


def test_create_line_chart_with_show_values(viz_tools):
    """Test line chart with value labels."""
    data = {"Jan": 100, "Feb": 150, "Mar": 200}

    with patch("matplotlib.pyplot.savefig"):
        result = viz_tools.create_line_chart(data, show_values=True, title="Line with Values")

        result_dict = json.loads(result)
        assert result_dict["status"] == "success"


def test_create_line_chart_timeseries(viz_tools):
    """Test line chart with timeseries detection."""
    data = {"2024-01-01": 100, "2024-02-01": 150, "2024-03-01": 200}

    with patch("matplotlib.pyplot.savefig"):
        result = viz_tools.create_line_chart(data, is_timeseries=True, title="Time Series")

        result_dict = json.loads(result)
        assert result_dict["status"] == "success"


def test_create_line_chart_with_annotations(viz_tools):
    """Test line chart with annotations."""
    data = {"Jan": 10, "Feb": 20, "Mar": 30}
    annotations = [{"x": 1, "y": 20, "text": "Turning point"}]

    with patch("matplotlib.pyplot.savefig"):
        result = viz_tools.create_line_chart(data, annotations=annotations, title="Annotated Line")

        result_dict = json.loads(result)
        assert result_dict["status"] == "success"


def test_create_multi_series_bar_chart(viz_tools):
    """Test multi-series grouped bar chart."""
    data = {
        "Q1": {"Jan": 100, "Feb": 120, "Mar": 140},
        "Q2": {"Jan": 110, "Feb": 130, "Mar": 150},
    }

    with patch("matplotlib.pyplot.savefig"):
        result = viz_tools.create_multi_series_chart(data, chart_type="bar", title="Quarterly Comparison")

        result_dict = json.loads(result)
        assert result_dict["status"] == "success"
        assert result_dict["chart_type"] == "multi_series_bar"
        assert result_dict["series_count"] == 2
        assert result_dict["categories"] == 3


def test_create_multi_series_stacked_bar_chart(viz_tools):
    """Test multi-series stacked bar chart."""
    data = {
        "Online": {"Jan": 100, "Feb": 120, "Mar": 140},
        "Offline": {"Jan": 80, "Feb": 90, "Mar": 100},
    }

    with patch("matplotlib.pyplot.savefig"):
        result = viz_tools.create_multi_series_chart(data, chart_type="stacked_bar", title="Sales by Channel")

        result_dict = json.loads(result)
        assert result_dict["status"] == "success"
        assert result_dict["chart_type"] == "multi_series_stacked_bar"


def test_create_multi_series_line_chart(viz_tools):
    """Test multi-series line chart."""
    data = {
        "Product A": {"Week 1": 100, "Week 2": 120, "Week 3": 140},
        "Product B": {"Week 1": 90, "Week 2": 110, "Week 3": 130},
    }

    with patch("matplotlib.pyplot.savefig"):
        result = viz_tools.create_multi_series_chart(data, chart_type="line", title="Product Trends")

        result_dict = json.loads(result)
        assert result_dict["status"] == "success"
        assert result_dict["chart_type"] == "multi_series_line"


def test_create_multi_series_with_colors(viz_tools):
    """Test multi-series chart with custom colors."""
    data = {
        "Series 1": {"A": 10, "B": 20},
        "Series 2": {"A": 15, "B": 25},
    }
    colors = ["red", "blue"]

    with patch("matplotlib.pyplot.savefig"):
        result = viz_tools.create_multi_series_chart(data, colors=colors, chart_type="bar", title="Colored Series")

        result_dict = json.loads(result)
        assert result_dict["status"] == "success"


def test_create_multi_series_with_show_values(viz_tools):
    """Test multi-series chart with value labels."""
    data = {
        "Series 1": {"A": 100, "B": 200},
        "Series 2": {"A": 150, "B": 250},
    }

    with patch("matplotlib.pyplot.savefig"):
        result = viz_tools.create_multi_series_chart(data, show_values=True, chart_type="bar", title="Values Shown")

        result_dict = json.loads(result)
        assert result_dict["status"] == "success"


def test_create_multi_series_with_list_data(viz_tools):
    """Test multi-series with list format data."""
    data = {
        "Series 1": [10, 20, 30],
        "Series 2": [15, 25, 35],
    }

    with patch("matplotlib.pyplot.savefig"):
        result = viz_tools.create_multi_series_chart(data, chart_type="line", title="List Data")

        result_dict = json.loads(result)
        assert result_dict["status"] == "success"


def test_multi_series_error_empty_data(viz_tools):
    """Test multi-series chart with empty data."""
    result = viz_tools.create_multi_series_chart({})

    result_dict = json.loads(result)
    assert result_dict["status"] == "error"
    assert "tip" in result_dict


def test_multi_series_error_invalid_chart_type(viz_tools):
    """Test multi-series with invalid chart type."""
    data = {"S1": {"A": 10}}
    result = viz_tools.create_multi_series_chart(data, chart_type="invalid")

    result_dict = json.loads(result)
    assert result_dict["status"] == "error"


def test_format_large_numbers(viz_tools):
    """Test large number formatting helper."""
    assert viz_tools._format_large_numbers(1_500_000_000) == "1.5B"
    assert viz_tools._format_large_numbers(2_300_000) == "2.3M"
    assert viz_tools._format_large_numbers(4_500) == "4.5K"
    assert viz_tools._format_large_numbers(123.45) == "123.5"
    assert viz_tools._format_large_numbers(0) == "0.0"


def test_parse_datetime(viz_tools):
    """Test datetime parsing helper."""
    dt = viz_tools._parse_datetime("2024-01-01")
    assert dt is not None
    assert dt.year == 2024
    assert dt.month == 1
    assert dt.day == 1

    dt = viz_tools._parse_datetime("01/15/2024")
    assert dt is not None

    dt = viz_tools._parse_datetime("not a date")
    assert dt is None


def test_validate_numeric_data(viz_tools):
    """Test numeric data validation helper."""
    # Valid data
    result = viz_tools._validate_numeric_data([1, 2, 3, 4])
    assert result == [1.0, 2.0, 3.0, 4.0]

    # Mixed valid and invalid
    result = viz_tools._validate_numeric_data([1, "2", 3, "bad", 5])
    assert len(result) == 4

    # All invalid
    with pytest.raises(ValueError, match="No valid numeric data found"):
        viz_tools._validate_numeric_data(["a", "b", "c"])

    # Empty list
    with pytest.raises(ValueError, match="empty"):
        viz_tools._validate_numeric_data([])


def test_multi_series_chart_enabled_flag(temp_output_dir):
    """Test that multi-series chart can be enabled/disabled."""
    tools_with = VisualizationTools(output_dir=temp_output_dir, enable_create_multi_series_chart=True)
    tools_without = VisualizationTools(output_dir=temp_output_dir, enable_create_multi_series_chart=False)

    with_names = [func.name for func in tools_with.functions.values()]
    without_names = [func.name for func in tools_without.functions.values()]

    assert "create_multi_series_chart" in with_names
    assert "create_multi_series_chart" not in without_names
