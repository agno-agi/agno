import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from agno.tools import Toolkit
from agno.utils.log import log_info, logger


class VisualizationTools(Toolkit):
    def __init__(
        self,
        output_dir: str = "charts",
        enable_create_bar_chart: bool = True,
        enable_create_line_chart: bool = True,
        enable_create_pie_chart: bool = True,
        enable_create_scatter_plot: bool = True,
        enable_create_histogram: bool = True,
        enable_create_multi_series_chart: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """
        Initialize the VisualizationTools toolkit.

        Args:
            output_dir (str): Directory to save charts. Default is "charts".
            enable_create_multi_series_chart (bool): Enable multi-series chart creation
        """
        # Check if matplotlib is available
        try:
            import matplotlib

            # Use non-interactive backend to avoid display issues
            matplotlib.use("Agg")
        except ImportError:
            raise ImportError("matplotlib is not installed. Please install it using: `pip install matplotlib`")

        # Create output directory if it doesn't exist
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        self.output_dir = output_dir

        tools: List[Any] = []
        if enable_create_bar_chart or all:
            tools.append(self.create_bar_chart)
        if enable_create_line_chart or all:
            tools.append(self.create_line_chart)
        if enable_create_pie_chart or all:
            tools.append(self.create_pie_chart)
        if enable_create_scatter_plot or all:
            tools.append(self.create_scatter_plot)
        if enable_create_histogram or all:
            tools.append(self.create_histogram)
        if enable_create_multi_series_chart or all:
            tools.append(self.create_multi_series_chart)

        super().__init__(name="visualization_tools", tools=tools, **kwargs)

    def _normalize_data_for_charts(
        self, data: Union[Dict[str, Any], List[Dict[str, Any]], List[Any], str]
    ) -> Dict[str, Union[int, float]]:
        """
        Normalize various data formats into a simple dictionary format for charts.

        Args:
            data: Can be a dict, list of dicts, or list of values

        Returns:
            Dict with string keys and numeric values
        """
        if isinstance(data, dict):
            # Already in the right format, just ensure values are numeric
            return {str(k): float(v) if isinstance(v, (int, float)) else 0 for k, v in data.items()}

        elif isinstance(data, list) and len(data) > 0:
            if isinstance(data[0], dict):
                # List of dictionaries - try to find key-value pairs
                result = {}
                for item in data:
                    if isinstance(item, dict):
                        # Look for common key patterns
                        keys = list(item.keys())
                        if len(keys) >= 2:
                            # Use first key as label, second as value
                            label_key = keys[0]
                            value_key = keys[1]
                            result[str(item[label_key])] = (
                                float(item[value_key]) if isinstance(item[value_key], (int, float)) else 0
                            )
                return result
            else:
                # List of values - create numbered keys
                return {f"Item {i + 1}": float(v) if isinstance(v, (int, float)) else 0 for i, v in enumerate(data)}

        # Fallback
        return {"Data": 1.0}

    def _format_large_numbers(self, value: float) -> str:
        """Format large numbers for better readability (e.g., 1.2M instead of 1200000)"""
        abs_value = abs(value)
        if abs_value >= 1_000_000_000:
            return f"{value / 1_000_000_000:.1f}B"
        elif abs_value >= 1_000_000:
            return f"{value / 1_000_000:.1f}M"
        elif abs_value >= 1_000:
            return f"{value / 1_000:.1f}K"
        else:
            return f"{value:.1f}"

    def _parse_datetime(self, value: str) -> Optional[datetime]:
        """Try to parse common datetime formats"""
        formats = [
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%d-%m-%Y",
            "%d/%m/%Y",
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
            "%m/%d/%Y",
            "%b %Y",
            "%B %Y",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(str(value), fmt)
            except (ValueError, TypeError):
                continue
        return None

    def _validate_numeric_data(self, data: List[Any], data_name: str = "data") -> List[float]:
        """Validate and convert data to numeric, providing helpful error messages"""
        if not isinstance(data, list):
            raise ValueError(f"Expected {data_name} to be a list, got {type(data).__name__}")
        
        if len(data) == 0:
            raise ValueError(f"{data_name} is empty. Please provide at least one data point.")

        numeric_data = []
        errors = []

        for i, value in enumerate(data):
            try:
                numeric_data.append(float(value))
            except (ValueError, TypeError):
                errors.append(f"Position {i}: '{value}' (type: {type(value).__name__})")

        if errors and len(numeric_data) == 0:
            error_msg = f"No valid numeric data found in {data_name}. Invalid values:\n" + "\n".join(errors[:5])
            if len(errors) > 5:
                error_msg += f"\n... and {len(errors) - 5} more"
            error_msg += "\n\nTip: Ensure all values are numbers (int or float)."
            raise ValueError(error_msg)

        if errors:
            logger.warning(f"Skipped {len(errors)} invalid values in {data_name}")

        return numeric_data

    def create_bar_chart(
        self,
        data: Union[Dict[str, Union[int, float]], List[Dict[str, Any]], str],
        title: str = "Bar Chart",
        x_label: str = "Categories",
        y_label: str = "Values",
        filename: Optional[str] = None,
        colors: Optional[List[str]] = None,
        show_values: bool = False,
        annotations: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Create a bar chart from the provided data.

        Args:
            data: Dictionary with categories as keys and values as numbers,
                  or list of dictionaries, or JSON string
            title (str): Title of the chart
            x_label (str): Label for x-axis
            y_label (str): Label for y-axis
            filename (Optional[str]): Custom filename for the chart image
            colors (Optional[List[str]]): List of colors for bars (hex codes or color names)
            show_values (bool): If True, display values on top of bars
            annotations (Optional[List[Dict]]): List of annotations with 'x', 'y', and 'text' keys

        Returns:
            str: JSON string with chart information and file path
        """
        try:
            import matplotlib.pyplot as plt

            # Handle string input (JSON)
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except json.JSONDecodeError:
                    pass

            # Normalize data format
            normalized_data = self._normalize_data_for_charts(data)

            # Prepare data
            categories = list(normalized_data.keys())
            values = list(normalized_data.values())

            # Create the chart
            plt.figure(figsize=(10, 6))
            bars = plt.bar(categories, values, color=colors if colors else None)
            plt.title(title, fontsize=14, fontweight="bold")
            plt.xlabel(x_label, fontsize=11)
            plt.ylabel(y_label, fontsize=11)

            # Auto-rotate labels if too many categories
            if len(categories) > 8:
                plt.xticks(rotation=45, ha="right")
            else:
                plt.xticks(rotation=0)

            # Show values on bars
            if show_values:
                for bar in bars:
                    height = bar.get_height()
                    plt.text(
                        bar.get_x() + bar.get_width() / 2.0,
                        height,
                        self._format_large_numbers(height),
                        ha="center",
                        va="bottom",
                        fontsize=9,
                    )

            # Add annotations
            if annotations:
                for anno in annotations:
                    if "x" in anno and "y" in anno and "text" in anno:
                        plt.annotate(
                            anno["text"],
                            xy=(anno["x"], anno["y"]),
                            xytext=(10, 10),
                            textcoords="offset points",
                            bbox=dict(boxstyle="round,pad=0.5", facecolor="yellow", alpha=0.7),
                            arrowprops=dict(arrowstyle="->", connectionstyle="arc3,rad=0"),
                        )

            plt.grid(axis="y", alpha=0.3)
            plt.tight_layout()

            # Save the chart
            if filename is None:
                filename = f"bar_chart_{len(os.listdir(self.output_dir)) + 1}.png"

            file_path = os.path.join(self.output_dir, filename)
            plt.savefig(file_path, dpi=300, bbox_inches="tight")
            plt.close()

            log_info(f"Bar chart created and saved to {file_path}")

            return json.dumps(
                {
                    "chart_type": "bar_chart",
                    "title": title,
                    "file_path": file_path,
                    "data_points": len(normalized_data),
                    "status": "success",
                }
            )

        except Exception as e:
            logger.error(f"Error creating bar chart: {str(e)}")
            return json.dumps({"chart_type": "bar_chart", "error": str(e), "status": "error"})

    def create_line_chart(
        self,
        data: Union[Dict[str, Union[int, float]], List[Dict[str, Any]], str],
        title: str = "Line Chart",
        x_label: str = "X-axis",
        y_label: str = "Y-axis",
        filename: Optional[str] = None,
        colors: Optional[List[str]] = None,
        show_values: bool = False,
        annotations: Optional[List[Dict[str, Any]]] = None,
        is_timeseries: bool = False,
    ) -> str:
        """
        Create a line chart from the provided data.

        Args:
            data: Dictionary with x-values as keys and y-values as numbers,
                  or list of dictionaries, or JSON string
            title (str): Title of the chart
            x_label (str): Label for x-axis
            y_label (str): Label for y-axis
            filename (Optional[str]): Custom filename for the chart image
            colors (Optional[List[str]]): List of colors for lines
            show_values (bool): If True, display values at data points
            annotations (Optional[List[Dict]]): List of annotations
            is_timeseries (bool): If True, try to parse x-values as dates

        Returns:
            str: JSON string with chart information and file path
        """
        try:
            import matplotlib.pyplot as plt

            # Handle string input (JSON)
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except json.JSONDecodeError:
                    pass

            # Normalize data format
            normalized_data = self._normalize_data_for_charts(data)

            # Prepare data
            x_values = list(normalized_data.keys())
            y_values = list(normalized_data.values())

            # Try to parse as datetime if requested
            use_datetime = False
            datetime_labels: List[str] = []
            if is_timeseries:
                datetime_values: List[Union[datetime, str]] = []
                for x in x_values:
                    dt = self._parse_datetime(x)
                    if dt:
                        datetime_values.append(dt)
                    else:
                        datetime_values.append(x)
                if all(isinstance(d, datetime) for d in datetime_values):
                    use_datetime = True
                    datetime_labels = [d.strftime("%Y-%m-%d") if isinstance(d, datetime) else str(d) for d in datetime_values]

            # Create the chart using numeric positions
            plt.figure(figsize=(10, 6))
            color = colors[0] if colors else None
            x_positions = list(range(len(y_values)))
            plt.plot(x_positions, y_values, marker="o", linewidth=2, markersize=6, color=color)
            plt.title(title, fontsize=14, fontweight="bold")
            plt.xlabel(x_label, fontsize=11)
            plt.ylabel(y_label, fontsize=11)

            # Set x-axis labels
            if use_datetime:
                plt.xticks(x_positions, datetime_labels, rotation=45, ha="right")
            elif len(x_values) > 8:
                plt.xticks(x_positions, x_values, rotation=45, ha="right")
            else:
                plt.xticks(x_positions, x_values)

            # Show values at points
            if show_values:
                for i, y in enumerate(y_values):
                    plt.text(float(i), y, self._format_large_numbers(y), ha="center", va="bottom", fontsize=8)

            # Add annotations
            if annotations:
                for anno in annotations:
                    if "x" in anno and "y" in anno and "text" in anno:
                        plt.annotate(
                            anno["text"],
                            xy=(anno["x"], anno["y"]),
                            xytext=(10, 10),
                            textcoords="offset points",
                            bbox=dict(boxstyle="round,pad=0.5", facecolor="yellow", alpha=0.7),
                            arrowprops=dict(arrowstyle="->", connectionstyle="arc3,rad=0"),
                        )

            plt.grid(True, alpha=0.3)
            plt.tight_layout()

            # Save the chart
            if filename is None:
                filename = f"line_chart_{len(os.listdir(self.output_dir)) + 1}.png"

            file_path = os.path.join(self.output_dir, filename)
            plt.savefig(file_path, dpi=300, bbox_inches="tight")
            plt.close()

            log_info(f"Line chart created and saved to {file_path}")

            return json.dumps(
                {
                    "chart_type": "line_chart",
                    "title": title,
                    "file_path": file_path,
                    "data_points": len(normalized_data),
                    "status": "success",
                }
            )

        except Exception as e:
            logger.error(f"Error creating line chart: {str(e)}")
            return json.dumps({"chart_type": "line_chart", "error": str(e), "status": "error"})

    def create_pie_chart(
        self,
        data: Union[Dict[str, Union[int, float]], List[Dict[str, Any]], str],
        title: str = "Pie Chart",
        filename: Optional[str] = None,
    ) -> str:
        """
        Create a pie chart from the provided data.

        Args:
            data: Dictionary with categories as keys and values as numbers,
                  or list of dictionaries, or JSON string
            title (str): Title of the chart
            filename (Optional[str]): Custom filename for the chart image

        Returns:
            str: JSON string with chart information and file path
        """
        try:
            import matplotlib.pyplot as plt

            # Handle string input (JSON)
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except json.JSONDecodeError:
                    pass

            # Normalize data format
            normalized_data = self._normalize_data_for_charts(data)

            # Prepare data
            labels = list(normalized_data.keys())
            values = list(normalized_data.values())

            # Create the chart
            plt.figure(figsize=(10, 8))
            plt.pie(values, labels=labels, autopct="%1.1f%%", startangle=90)
            plt.title(title)
            plt.axis("equal")  # Equal aspect ratio ensures that pie is drawn as a circle

            # Save the chart
            if filename is None:
                filename = f"pie_chart_{len(os.listdir(self.output_dir)) + 1}.png"

            file_path = os.path.join(self.output_dir, filename)
            plt.savefig(file_path, dpi=300, bbox_inches="tight")
            plt.close()

            log_info(f"Pie chart created and saved to {file_path}")

            return json.dumps(
                {
                    "chart_type": "pie_chart",
                    "title": title,
                    "file_path": file_path,
                    "data_points": len(normalized_data),
                    "status": "success",
                }
            )

        except Exception as e:
            logger.error(f"Error creating pie chart: {str(e)}")
            return json.dumps({"chart_type": "pie_chart", "error": str(e), "status": "error"})

    def create_scatter_plot(
        self,
        x_data: Optional[List[Union[int, float]]] = None,
        y_data: Optional[List[Union[int, float]]] = None,
        title: str = "Scatter Plot",
        x_label: str = "X-axis",
        y_label: str = "Y-axis",
        filename: Optional[str] = None,
        # Alternative parameter names that agents might use
        x: Optional[List[Union[int, float]]] = None,
        y: Optional[List[Union[int, float]]] = None,
        data: Optional[Union[List[List[Union[int, float]]], Dict[str, List[Union[int, float]]]]] = None,
    ) -> str:
        """
        Create a scatter plot from the provided data.

        Args:
            x_data: List of x-values (can also use 'x' parameter)
            y_data: List of y-values (can also use 'y' parameter)
            title (str): Title of the chart
            x_label (str): Label for x-axis
            y_label (str): Label for y-axis
            filename (Optional[str]): Custom filename for the chart image
            data: Alternative format - list of [x,y] pairs or dict with 'x' and 'y' keys

        Returns:
            str: JSON string with chart information and file path
        """
        try:
            import matplotlib.pyplot as plt

            # Handle different parameter formats
            if x_data is None:
                x_data = x
            if y_data is None:
                y_data = y

            # Handle data parameter
            if data is not None:
                if isinstance(data, dict):
                    if "x" in data and "y" in data:
                        x_data = data["x"]
                        y_data = data["y"]
                elif isinstance(data, list) and len(data) > 0:
                    if isinstance(data[0], list) and len(data[0]) == 2:
                        # List of [x,y] pairs
                        x_data = [point[0] for point in data]
                        y_data = [point[1] for point in data]

            # Validate that we have data
            if x_data is None or y_data is None:
                raise ValueError("Missing x_data and y_data parameters")

            if len(x_data) != len(y_data):
                raise ValueError("x_data and y_data must have the same length")

            # Create the chart
            plt.figure(figsize=(10, 6))
            plt.scatter(x_data, y_data, alpha=0.7, s=50)
            plt.title(title)
            plt.xlabel(x_label)
            plt.ylabel(y_label)
            plt.grid(True, alpha=0.3)
            plt.tight_layout()

            # Save the chart
            if filename is None:
                filename = f"scatter_plot_{len(os.listdir(self.output_dir)) + 1}.png"

            file_path = os.path.join(self.output_dir, filename)
            plt.savefig(file_path, dpi=300, bbox_inches="tight")
            plt.close()

            log_info(f"Scatter plot created and saved to {file_path}")

            return json.dumps(
                {
                    "chart_type": "scatter_plot",
                    "title": title,
                    "file_path": file_path,
                    "data_points": len(x_data),
                    "status": "success",
                }
            )

        except Exception as e:
            logger.error(f"Error creating scatter plot: {str(e)}")
            return json.dumps({"chart_type": "scatter_plot", "error": str(e), "status": "error"})

    def create_histogram(
        self,
        data: List[Union[int, float]],
        bins: int = 10,
        title: str = "Histogram",
        x_label: str = "Values",
        y_label: str = "Frequency",
        filename: Optional[str] = None,
    ) -> str:
        """
        Create a histogram from the provided data.

        Args:
            data: List of numeric values to plot
            bins (int): Number of bins for the histogram
            title (str): Title of the chart
            x_label (str): Label for x-axis
            y_label (str): Label for y-axis
            filename (Optional[str]): Custom filename for the chart image

        Returns:
            str: JSON string with chart information and file path
        """
        try:
            import matplotlib.pyplot as plt

            # Validate data
            if not isinstance(data, list) or len(data) == 0:
                raise ValueError("Data must be a non-empty list of numbers")

            # Convert to numeric values
            numeric_data = []
            for value in data:
                try:
                    numeric_data.append(float(value))
                except (ValueError, TypeError):
                    continue

            if len(numeric_data) == 0:
                raise ValueError("No valid numeric data found")

            # Create the chart
            plt.figure(figsize=(10, 6))
            plt.hist(numeric_data, bins=bins, alpha=0.7, edgecolor="black")
            plt.title(title)
            plt.xlabel(x_label)
            plt.ylabel(y_label)
            plt.grid(True, alpha=0.3)
            plt.tight_layout()

            # Save the chart
            if filename is None:
                filename = f"histogram_{len(os.listdir(self.output_dir)) + 1}.png"

            file_path = os.path.join(self.output_dir, filename)
            plt.savefig(file_path, dpi=300, bbox_inches="tight")
            plt.close()

            log_info(f"Histogram created and saved to {file_path}")

            return json.dumps(
                {
                    "chart_type": "histogram",
                    "title": title,
                    "file_path": file_path,
                    "data_points": len(numeric_data),
                    "bins": bins,
                    "status": "success",
                }
            )

        except Exception as e:
            logger.error(f"Error creating histogram: {str(e)}")
            return json.dumps({"chart_type": "histogram", "error": str(e), "status": "error"})

    def create_multi_series_chart(
        self,
        data: Dict[str, Union[Dict[str, Union[int, float]], List[Union[int, float]]]],
        chart_type: str = "bar",
        title: str = "Multi-Series Chart",
        x_label: str = "Categories",
        y_label: str = "Values",
        filename: Optional[str] = None,
        colors: Optional[List[str]] = None,
        show_values: bool = False,
        show_legend: bool = True,
        is_timeseries: bool = False,
    ) -> str:
        """
        Create a chart with multiple data series (grouped bars, multiple lines, etc.).

        Args:
            data: Dictionary where keys are series names and values are data for each series.
                  Format: {"Series1": {"A": 10, "B": 20}, "Series2": {"A": 15, "B": 25}}
                  Or: {"Series1": [10, 20, 30], "Series2": [15, 25, 35]}
            chart_type (str): Type of chart - "bar" (grouped), "line", or "stacked_bar"
            title (str): Title of the chart
            x_label (str): Label for x-axis
            y_label (str): Label for y-axis
            filename (Optional[str]): Custom filename for the chart image
            colors (Optional[List[str]]): List of colors for each series
            show_values (bool): If True, display values on bars/points
            show_legend (bool): If True, display legend
            is_timeseries (bool): If True, treat x-axis as dates

        Returns:
            str: JSON string with chart information and file path
        """
        try:
            import matplotlib.pyplot as plt
            import numpy as np

            # Validate data
            if not isinstance(data, dict) or len(data) == 0:
                raise ValueError(
                    "Data must be a non-empty dictionary with series names as keys. "
                    "Example: {'Q1': {'Jan': 100, 'Feb': 120}, 'Q2': {'Jan': 110, 'Feb': 130}}"
                )

            # Extract series
            series_names = list(data.keys())

            # Normalize each series
            normalized_series = {}
            categories = None

            for series_name, series_data in data.items():
                if isinstance(series_data, dict):
                    normalized = self._normalize_data_for_charts(series_data)
                    normalized_series[series_name] = normalized
                    if categories is None:
                        categories = list(normalized.keys())
                elif isinstance(series_data, list):
                    # Convert list to dict with numbered keys
                    normalized_series[series_name] = {f"Point {i + 1}": float(v) for i, v in enumerate(series_data)}
                    if categories is None:
                        categories = list(normalized_series[series_name].keys())

            if not categories:
                raise ValueError("Could not extract categories from data")

            # Parse dates if timeseries
            x_positions = list(range(len(categories)))
            display_labels: List[str] = categories
            use_datetime = False

            if is_timeseries:
                parsed_dates: List[Union[datetime, str]] = []
                for cat in categories:
                    dt = self._parse_datetime(cat)
                    parsed_dates.append(dt if dt else cat)
                if all(isinstance(d, datetime) for d in parsed_dates):
                    use_datetime = True
                    display_labels = [d.strftime("%Y-%m-%d") if isinstance(d, datetime) else str(d) for d in parsed_dates]

            # Create the chart
            plt.figure(figsize=(12, 6))

            if chart_type == "bar":
                # Grouped bar chart
                bar_width = 0.8 / len(series_names)

                for i, series_name in enumerate(series_names):
                    values = [normalized_series[series_name].get(cat, 0) for cat in categories]
                    x_pos = [x + i * bar_width for x in x_positions]
                    color = colors[i] if colors and i < len(colors) else None
                    bars = plt.bar(x_pos, values, bar_width, label=series_name, color=color)

                    if show_values:
                        for bar in bars:
                            height = bar.get_height()
                            plt.text(
                                bar.get_x() + bar.get_width() / 2.0,
                                height,
                                self._format_large_numbers(height),
                                ha="center",
                                va="bottom",
                                fontsize=8,
                            )

                plt.xticks([x + bar_width * (len(series_names) - 1) / 2 for x in x_positions], display_labels)

            elif chart_type == "stacked_bar":
                # Stacked bar chart
                bottom = np.zeros(len(categories))

                for i, series_name in enumerate(series_names):
                    values = [normalized_series[series_name].get(cat, 0) for cat in categories]
                    color = colors[i] if colors and i < len(colors) else None
                    bars = plt.bar(x_positions, values, label=series_name, bottom=bottom, color=color)

                    if show_values:
                        for j, (bar, val) in enumerate(zip(bars, values)):
                            if val > 0:  # Only show non-zero values
                                plt.text(
                                    bar.get_x() + bar.get_width() / 2.0,
                                    bottom[j] + val / 2,
                                    self._format_large_numbers(val),
                                    ha="center",
                                    va="center",
                                    fontsize=8,
                                )
                    bottom += np.array(values)

                plt.xticks(x_positions, display_labels)

            elif chart_type == "line":
                # Multiple line chart
                for i, series_name in enumerate(series_names):
                    values = [normalized_series[series_name].get(cat, 0) for cat in categories]
                    color = colors[i] if colors and i < len(colors) else None
                    plt.plot(
                        x_positions,
                        values,
                        marker="o",
                        linewidth=2,
                        markersize=6,
                        label=series_name,
                        color=color,
                    )

                    if show_values:
                        for j, y in enumerate(values):
                            plt.text(float(j), y, self._format_large_numbers(y), ha="center", va="bottom", fontsize=7)

                plt.xticks(x_positions, display_labels)
                if len(categories) > 8 or use_datetime:
                    plt.xticks(rotation=45, ha="right")
            else:
                raise ValueError(f"Invalid chart_type: {chart_type}. Must be 'bar', 'stacked_bar', or 'line'")

            plt.title(title, fontsize=14, fontweight="bold")
            plt.xlabel(x_label, fontsize=11)
            plt.ylabel(y_label, fontsize=11)

            if show_legend and len(series_names) > 1:
                plt.legend(loc="best", framealpha=0.9)

            plt.grid(axis="y", alpha=0.3)
            plt.tight_layout()

            # Save the chart
            if filename is None:
                filename = f"multi_series_{chart_type}_{len(os.listdir(self.output_dir)) + 1}.png"

            file_path = os.path.join(self.output_dir, filename)
            plt.savefig(file_path, dpi=300, bbox_inches="tight")
            plt.close()

            log_info(f"Multi-series {chart_type} chart created and saved to {file_path}")

            return json.dumps(
                {
                    "chart_type": f"multi_series_{chart_type}",
                    "title": title,
                    "file_path": file_path,
                    "series_count": len(series_names),
                    "categories": len(categories),
                    "series_names": series_names,
                    "status": "success",
                }
            )

        except ValueError as e:
            logger.error(f"Validation error in multi-series chart: {str(e)}")
            return json.dumps(
                {
                    "chart_type": "multi_series_chart",
                    "error": str(e),
                    "status": "error",
                    "tip": "Ensure data is in format: {'Series1': {'Cat1': 10, 'Cat2': 20}, 'Series2': {...}}",
                }
            )
        except Exception as e:
            logger.error(f"Error creating multi-series chart: {str(e)}")
            return json.dumps({"chart_type": "multi_series_chart", "error": str(e), "status": "error"})
