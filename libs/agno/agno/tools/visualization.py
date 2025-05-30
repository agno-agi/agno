import json
import os
from typing import Any, Dict, List, Optional, Union

from agno.tools import Toolkit
from agno.utils.log import log_info, logger


class VisualizationTools(Toolkit):
    def __init__(
        self,
        bar_chart: bool = True,
        line_chart: bool = True,
        pie_chart: bool = True,
        scatter_plot: bool = True,
        histogram: bool = True,
        enable_all: bool = False,
        output_dir: str = "charts",
        **kwargs,
    ):
        """
        Initialize the VisualizationTools toolkit.

        Args:
            bar_chart (bool): Enable bar chart creation. Default is True.
            line_chart (bool): Enable line chart creation. Default is True.
            pie_chart (bool): Enable pie chart creation. Default is True.
            scatter_plot (bool): Enable scatter plot creation. Default is True.
            histogram (bool): Enable histogram creation. Default is True.
            enable_all (bool): Enable all chart types. Default is False.
            output_dir (str): Directory to save charts. Default is "charts".
        """
        super().__init__(**kwargs)

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

        # Register functions based on enabled chart types
        if enable_all:
            bar_chart = line_chart = pie_chart = scatter_plot = histogram = True

        if bar_chart:
            self.register(self.create_bar_chart)
        if line_chart:
            self.register(self.create_line_chart)
        if pie_chart:
            self.register(self.create_pie_chart)
        if scatter_plot:
            self.register(self.create_scatter_plot)
        if histogram:
            self.register(self.create_histogram)

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

    def create_bar_chart(
        self,
        data: Union[Dict[str, Union[int, float]], List[Dict[str, Any]], str],
        title: str = "Bar Chart",
        x_label: str = "Categories",
        y_label: str = "Values",
        filename: Optional[str] = None,
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
            plt.bar(categories, values)
            plt.title(title)
            plt.xlabel(x_label)
            plt.ylabel(y_label)
            plt.xticks(rotation=45, ha="right")
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

            # Create the chart
            plt.figure(figsize=(10, 6))
            plt.plot(x_values, y_values, marker="o", linewidth=2, markersize=6)
            plt.title(title)
            plt.xlabel(x_label)
            plt.ylabel(y_label)
            plt.xticks(rotation=45, ha="right")
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
