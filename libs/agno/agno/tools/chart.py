import json
from enum import Enum
from textwrap import dedent
from typing import Callable, Dict, List, Optional, Union

from typing_extensions import NotRequired, TypedDict

from agno.tools import Toolkit
from agno.utils.log import log_debug

ChartDataValue = Union[str, int, float]
ChartDataRow = Dict[str, ChartDataValue]


class ChartType(str, Enum):
    """Supported Agno OS inline chart renderers."""

    BAR = "bar"
    LINE = "line"
    AREA = "area"
    PIE = "pie"
    BAR_HORIZONTAL = "bar-horizontal"
    BAR_STACKED = "bar-stacked"
    AREA_STACKED = "area-stacked"


# Chart types that plot categories/dates on an axis and need xKey/yKeys.
CARTESIAN_CHART_TYPES = {
    ChartType.BAR,
    ChartType.LINE,
    ChartType.AREA,
    ChartType.BAR_HORIZONTAL,
    ChartType.BAR_STACKED,
    ChartType.AREA_STACKED,
}


class ChartSeriesConfig(TypedDict):
    """Display metadata for a chart series."""

    # Human-readable label shown in legends and tooltips.
    label: str

    # Optional explicit series color. Omit to use theme-aware chart colors.
    color: NotRequired[str]


class ChartSpec(TypedDict):
    """Chart payload shape rendered inline by Agno OS."""

    # Selects the frontend renderer, for example line, bar, area, or pie.
    type: str

    # Flat chart rows. Labels/dates should be strings; measured values should be numbers.
    data: List[ChartDataRow]

    # Series metadata keyed by data field, for example {"revenue": {"label": "Revenue"}}.
    config: Dict[str, ChartSeriesConfig]

    # Optional chart heading shown above the visualization.
    title: NotRequired[str]

    # Optional supporting copy shown with the chart.
    description: NotRequired[str]

    # Cartesian chart category/date key, for example "month" or "date".
    xKey: NotRequired[str]

    # Explicit cartesian series order. If absent, frontend can infer from config keys.
    yKeys: NotRequired[List[str]]

    # Pie chart label key, for example "provider" or "model".
    nameKey: NotRequired[str]

    # Pie chart numeric value key, for example "runs" or "tokens".
    valueKey: NotRequired[str]


class ChartTools(Toolkit):
    """Toolkit that builds validated chart blocks Agno OS renders inline in chat."""

    DEFAULT_INSTRUCTIONS = dedent("""\
        You can render interactive charts inline in your responses.

        When the user asks for trends, comparisons, usage, costs, performance, or
        any answer that benefits from a visualization, call the `create_chart`
        tool with the chart data. The tool validates the data and returns a
        fenced `chart` code block.

        Rules:
        - Include the returned `chart` block verbatim in your markdown response.
          Do not modify, reformat, or wrap it.
        - Add one short sentence before the chart describing what it shows, and
          one short sentence after it with the key takeaway.
        - Do not return tables that duplicate the chart data unless asked.
        - Keep the data compact enough to inspect in chat. Aggregate or sample
          if the raw dataset is large.
        - If the tool returns a validation error, fix the data and call it again.
    """)

    def __init__(
        self,
        instructions: Optional[str] = None,
        add_instructions: bool = True,
        **kwargs,
    ):
        self.instructions = instructions if instructions is not None else self.DEFAULT_INSTRUCTIONS

        tools: List[Callable] = [self.create_chart]

        super().__init__(
            name="chart_tools",
            tools=tools,
            instructions=self.instructions,
            add_instructions=add_instructions,
            **kwargs,
        )

    def create_chart(
        self,
        chart_type: str,
        data: List[Dict[str, Union[str, int, float]]],
        config: Dict[str, str],
        title: Optional[str] = None,
        description: Optional[str] = None,
        x_key: Optional[str] = None,
        y_keys: Optional[List[str]] = None,
        name_key: Optional[str] = None,
        value_key: Optional[str] = None,
    ) -> str:
        """Build a chart block that Agno OS renders inline in the chat. Include the
        returned fenced block verbatim in your markdown response.

        Args:
            chart_type (str): One of "bar", "line", "area", "pie", "bar-horizontal", "bar-stacked", "area-stacked".
            data (List[Dict[str, Union[str, int, float]]]): Flat rows, for example [{"month": "Jan", "revenue": 4000}]. Use strings for labels/dates and numbers for measured values.
            config (Dict[str, str]): Maps each series key to its display label, for example {"revenue": "Revenue ($)"}.
            title (Optional[str]): Optional heading shown above the chart.
            description (Optional[str]): Optional supporting copy shown with the chart.
            x_key (Optional[str]): Category or date field for cartesian charts, for example "month". Required for non-pie charts.
            y_keys (Optional[List[str]]): Explicit series order for cartesian charts. Defaults to the config keys.
            name_key (Optional[str]): Slice label field for pie charts, for example "provider". Required for pie charts.
            value_key (Optional[str]): Numeric slice value field for pie charts, for example "runs". Required for pie charts.

        Returns:
            str: A fenced ```chart block to include verbatim in the response, or an error message starting with "Chart validation failed".
        """
        try:
            spec = self._build_spec(
                chart_type=chart_type,
                data=data,
                config=config,
                title=title,
                description=description,
                x_key=x_key,
                y_keys=y_keys,
                name_key=name_key,
                value_key=value_key,
            )
        except ValueError as e:
            return f"Chart validation failed: {e}. Fix the arguments and call create_chart again."

        log_debug(f"Created {chart_type} chart with {len(data)} rows")
        return f"```chart\n{json.dumps(spec, indent=2)}\n```"

    def _build_spec(
        self,
        chart_type: str,
        data: List[Dict[str, Union[str, int, float]]],
        config: Dict[str, str],
        title: Optional[str],
        description: Optional[str],
        x_key: Optional[str],
        y_keys: Optional[List[str]],
        name_key: Optional[str],
        value_key: Optional[str],
    ) -> ChartSpec:
        """Validate the chart arguments and assemble the Agno OS chart spec."""
        try:
            resolved_type = ChartType(chart_type)
        except ValueError:
            valid_types = ", ".join(t.value for t in ChartType)
            raise ValueError(f"unknown chart_type '{chart_type}'. Use one of: {valid_types}")

        if not data:
            raise ValueError("data must be a non-empty list of rows")
        if not config:
            raise ValueError("config must map each series key to a label")

        data = [self._validate_row(row, index) for index, row in enumerate(data)]

        row_keys = set().union(*(row.keys() for row in data))
        missing_config_keys = [key for key in config if key not in row_keys]
        if missing_config_keys:
            raise ValueError(f"config keys not present in data rows: {missing_config_keys}")

        spec: ChartSpec = {
            "type": resolved_type.value,
            "data": data,
            "config": {key: ChartSeriesConfig(label=label) for key, label in config.items()},
        }
        if title is not None:
            spec["title"] = title
        if description is not None:
            spec["description"] = description

        if resolved_type == ChartType.PIE:
            if not name_key or not value_key:
                raise ValueError("pie charts require both name_key and value_key")
            self._require_key(data, name_key, "name_key")
            self._require_numeric_key(data, value_key, "value_key")
            if value_key not in config:
                raise ValueError(f"config must include a label for value_key '{value_key}'")
            spec["nameKey"] = name_key
            spec["valueKey"] = value_key
        else:
            if not x_key:
                raise ValueError(f"{resolved_type.value} charts require x_key for the category or date field")
            self._require_key(data, x_key, "x_key")
            resolved_y_keys = y_keys if y_keys else [key for key in config if key != x_key]
            if not resolved_y_keys:
                raise ValueError("no series keys found: provide y_keys or config keys other than x_key")
            for key in resolved_y_keys:
                self._require_numeric_key(data, key, "y_keys")
            spec["xKey"] = x_key
            spec["yKeys"] = resolved_y_keys

        return spec

    def _validate_row(self, row: Dict[str, Union[str, int, float]], index: int) -> ChartDataRow:
        """Check a data row is a flat object of strings and numbers."""
        if not isinstance(row, dict):
            raise ValueError(f"data[{index}] must be an object, got {type(row).__name__}")

        for key, value in row.items():
            if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                raise ValueError(
                    f"data[{index}]['{key}'] must be a string or number, got {type(value).__name__}. "
                    "Rows must be flat objects."
                )
        return row

    @staticmethod
    def _coerce_number(value: str) -> ChartDataValue:
        """Convert numeric strings to numbers so values are never stringified."""
        try:
            as_float = float(value)
        except ValueError:
            return value
        return int(as_float) if as_float.is_integer() and "." not in value and "e" not in value.lower() else as_float

    @staticmethod
    def _require_key(data: List[ChartDataRow], key: str, arg_name: str) -> None:
        missing = [index for index, row in enumerate(data) if key not in row]
        if missing:
            raise ValueError(f"{arg_name} '{key}' is missing from data rows at indexes {missing[:5]}")

    def _require_numeric_key(self, data: List[ChartDataRow], key: str, arg_name: str) -> None:
        """Check a series key is numeric in every row, coercing stringified numbers in place."""
        for index, row in enumerate(data):
            if key not in row:
                raise ValueError(f"{arg_name} '{key}' is missing from data[{index}]")
            value = row[key]
            if isinstance(value, str):
                value = self._coerce_number(value)
                row[key] = value
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(
                    f"{arg_name} '{key}' must be numeric in every row; data[{index}]['{key}'] is '{row[key]}'"
                )
