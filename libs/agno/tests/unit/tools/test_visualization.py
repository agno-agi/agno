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
    return VisualizationTools(output_dir=temp_output_dir, enable_all=True)


@pytest.fixture
def basic_viz_tools(temp_output_dir):
    """Create a VisualizationTools instance with only basic chart types."""
    return VisualizationTools(output_dir=temp_output_dir)


def test_initialization_with_selective_charts(temp_output_dir):
    """Test initialization with only selected chart types."""
    tools = VisualizationTools(
        output_dir=temp_output_dir,
        bar_chart=True,
        line_chart=True,
        pie_chart=False,
        scatter_plot=False,
        histogram=True,
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
    
    result = viz_tools.create_bar_chart(
        data=test_data,
        title="Test Chart",
        x_label="Categories",
        y_label="Values"
    )
    
    result_dict = json.loads(result)
    
    assert result_dict["status"] == "success"
    assert result_dict["chart_type"] == "bar_chart"
    assert result_dict["title"] == "Test Chart"
    assert result_dict["data_points"] == 3
    assert "file_path" in result_dict
    
    # Verify matplotlib functions were called
    mock_figure.assert_called_once_with(figsize=(10, 6))
    mock_bar.assert_called_once()
    mock_title.assert_called_once_with("Test Chart")
    mock_xlabel.assert_called_once_with("Categories")
    mock_ylabel.assert_called_once_with("Values")
    mock_savefig.assert_called_once()
    mock_close.assert_called_once()


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
    
    result = viz_tools.create_line_chart(
        data=test_data,
        title="Monthly Trend",
        x_label="Month",
        y_label="Sales"
    )
    
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
    
    result = viz_tools.create_pie_chart(
        data=test_data,
        title="Color Distribution"
    )
    
    result_dict = json.loads(result)
    
    assert result_dict["status"] == "success"
    assert result_dict["chart_type"] == "pie_chart"
    assert result_dict["title"] == "Color Distribution"
    assert result_dict["data_points"] == 4
    
    # Verify matplotlib functions were called
    mock_figure.assert_called_once_with(figsize=(10, 8))
    mock_pie.assert_called_once()
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
    y_data = [2, 4, 1, 5, 3]
    
    result = viz_tools.create_scatter_plot(
        x_data=x_data,
        y_data=y_data,
        title="Correlation Analysis",
        x_label="X Values",
        y_label="Y Values"
    )
    
    result_dict = json.loads(result)
    
    assert result_dict["status"] == "success"
    assert result_dict["chart_type"] == "scatter_plot"
    assert result_dict["title"] == "Correlation Analysis"
    assert result_dict["data_points"] == 5
    
    # Verify matplotlib functions were called
    mock_figure.assert_called_once_with(figsize=(10, 6))
    mock_scatter.assert_called_once_with(x_data, y_data, alpha=0.6)


def test_scatter_plot_mismatched_data_length(viz_tools):
    """Test scatter plot with mismatched x and y data lengths."""
    x_data = [1, 2, 3]
    y_data = [1, 2]  # Different length
    
    result = viz_tools.create_scatter_plot(
        x_data=x_data,
        y_data=y_data,
        title="Test"
    )
    
    result_dict = json.loads(result)
    
    assert result_dict["status"] == "error"
    assert "x_data and y_data must have the same length" in result_dict["error"]


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
        data=test_data,
        bins=5,
        title="Distribution",
        x_label="Values",
        y_label="Frequency"
    )
    
    result_dict = json.loads(result)
    
    assert result_dict["status"] == "success"
    assert result_dict["chart_type"] == "histogram"
    assert result_dict["title"] == "Distribution"
    assert result_dict["data_points"] == 9
    assert result_dict["bins"] == 5
    
    # Verify matplotlib functions were called
    mock_figure.assert_called_once_with(figsize=(10, 6))
    mock_hist.assert_called_once_with(test_data, bins=5, alpha=0.7, edgecolor='black')


def test_custom_filename(viz_tools):
    """Test chart creation with custom filename."""
    with patch("matplotlib.pyplot.savefig"), \
         patch("matplotlib.pyplot.close"), \
         patch("matplotlib.pyplot.figure"), \
         patch("matplotlib.pyplot.bar"), \
         patch("matplotlib.pyplot.title"), \
         patch("matplotlib.pyplot.xlabel"), \
         patch("matplotlib.pyplot.ylabel"), \
         patch("matplotlib.pyplot.xticks"), \
         patch("matplotlib.pyplot.tight_layout"):
        
        test_data = {"A": 10, "B": 20}
        custom_filename = "custom_chart.png"
        
        result = viz_tools.create_bar_chart(
            data=test_data,
            filename=custom_filename
        )
        
        result_dict = json.loads(result)
        assert custom_filename in result_dict["file_path"]


@patch("matplotlib.pyplot.savefig", side_effect=Exception("Save failed"))
def test_error_handling(mock_savefig, viz_tools):
    """Test error handling when chart creation fails."""
    test_data = {"A": 10, "B": 20}
    
    result = viz_tools.create_bar_chart(data=test_data)
    result_dict = json.loads(result)
    
    assert result_dict["status"] == "error"
    assert "Save failed" in result_dict["error"]


def test_matplotlib_import_error():
    """Test initialization when matplotlib is not available."""
    with patch.dict("sys.modules", {"matplotlib": None}):
        with pytest.raises(ImportError, match="matplotlib.*not installed"):
            VisualizationTools()


def test_basic_initialization_has_correct_functions(basic_viz_tools):
    """Test that basic initialization includes default chart types."""
    function_names = [func.name for func in basic_viz_tools.functions.values()]
    
    # Should include default enabled charts
    assert "create_bar_chart" in function_names
    assert "create_line_chart" in function_names
    assert "create_pie_chart" in function_names
    assert "create_scatter_plot" in function_names
    assert "create_histogram" in function_names 