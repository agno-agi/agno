"""Unit tests for ChartTools class."""

import json

import pytest

from agno.tools.chart import ChartTools, ChartType


@pytest.fixture
def chart_tools():
    """Create a ChartTools instance."""
    return ChartTools()


def parse_chart_block(result: str) -> dict:
    """Extract and parse the JSON payload from a fenced chart block."""
    assert result.startswith("```chart\n"), f"expected a fenced chart block, got: {result[:80]}"
    assert result.endswith("\n```")
    return json.loads(result[len("```chart\n") : -len("\n```")])


def test_initialization_registers_create_chart(chart_tools):
    function_names = [func.name for func in chart_tools.functions.values()]
    assert function_names == ["create_chart"]


def test_default_instructions_attached(chart_tools):
    assert chart_tools.add_instructions is True
    assert "create_chart" in chart_tools.instructions


def test_custom_instructions_override():
    tools = ChartTools(instructions="Custom chart rules.")
    assert tools.instructions == "Custom chart rules."


def test_bar_chart_happy_path(chart_tools):
    result = chart_tools.create_chart(
        chart_type="bar",
        data=[
            {"month": "Jan", "revenue": 4000, "expenses": 2400},
            {"month": "Feb", "revenue": 3000, "expenses": 1398},
        ],
        config={"revenue": "Revenue ($)", "expenses": "Expenses ($)"},
        title="Monthly Revenue",
        description="Revenue and expenses by month",
        x_key="month",
    )
    spec = parse_chart_block(result)

    assert spec["type"] == "bar"
    assert spec["title"] == "Monthly Revenue"
    assert spec["description"] == "Revenue and expenses by month"
    assert spec["data"] == [
        {"month": "Jan", "revenue": 4000, "expenses": 2400},
        {"month": "Feb", "revenue": 3000, "expenses": 1398},
    ]
    assert spec["config"] == {"revenue": {"label": "Revenue ($)"}, "expenses": {"label": "Expenses ($)"}}
    assert spec["xKey"] == "month"
    assert spec["yKeys"] == ["revenue", "expenses"]


def test_pie_chart_happy_path(chart_tools):
    result = chart_tools.create_chart(
        chart_type="pie",
        data=[{"provider": "openai", "runs": 12}, {"provider": "anthropic", "runs": 30}],
        config={"runs": "Runs"},
        name_key="provider",
        value_key="runs",
    )
    spec = parse_chart_block(result)

    assert spec["type"] == "pie"
    assert spec["nameKey"] == "provider"
    assert spec["valueKey"] == "runs"
    assert "xKey" not in spec
    assert "yKeys" not in spec


def test_explicit_y_keys_are_preserved(chart_tools):
    result = chart_tools.create_chart(
        chart_type="line",
        data=[{"day": "Mon", "input": 10, "output": 20}],
        config={"input": "Input", "output": "Output"},
        x_key="day",
        y_keys=["output", "input"],
    )
    spec = parse_chart_block(result)
    assert spec["yKeys"] == ["output", "input"]


def test_y_keys_default_excludes_x_key(chart_tools):
    result = chart_tools.create_chart(
        chart_type="area",
        data=[{"day": "Mon", "runs": 5}],
        config={"day": "Day", "runs": "Runs"},
        x_key="day",
    )
    spec = parse_chart_block(result)
    assert spec["yKeys"] == ["runs"]


def test_stringified_numbers_are_coerced(chart_tools):
    result = chart_tools.create_chart(
        chart_type="bar",
        data=[{"month": "Jan", "revenue": "4000"}, {"month": "Feb", "revenue": "3000.5"}],
        config={"revenue": "Revenue"},
        x_key="month",
    )
    spec = parse_chart_block(result)
    assert spec["data"][0]["revenue"] == 4000
    assert spec["data"][1]["revenue"] == 3000.5


def test_numeric_looking_labels_stay_strings(chart_tools):
    result = chart_tools.create_chart(
        chart_type="line",
        data=[{"year": "2024", "runs": 5}, {"year": "2025", "runs": 9}],
        config={"runs": "Runs"},
        x_key="year",
    )
    spec = parse_chart_block(result)
    assert spec["data"][0]["year"] == "2024"
    assert spec["data"][1]["year"] == "2025"


def test_optional_fields_omitted_when_absent(chart_tools):
    result = chart_tools.create_chart(
        chart_type="bar",
        data=[{"month": "Jan", "revenue": 1}],
        config={"revenue": "Revenue"},
        x_key="month",
    )
    spec = parse_chart_block(result)
    assert "title" not in spec
    assert "description" not in spec
    assert "nameKey" not in spec
    assert "valueKey" not in spec


@pytest.mark.parametrize("chart_type", [t.value for t in ChartType if t != ChartType.PIE])
def test_all_cartesian_types_render(chart_tools, chart_type):
    result = chart_tools.create_chart(
        chart_type=chart_type,
        data=[{"month": "Jan", "value": 1}],
        config={"value": "Value"},
        x_key="month",
    )
    spec = parse_chart_block(result)
    assert spec["type"] == chart_type


def test_unknown_chart_type_fails(chart_tools):
    result = chart_tools.create_chart(
        chart_type="donut",
        data=[{"a": "x", "b": 1}],
        config={"b": "B"},
        x_key="a",
    )
    assert result.startswith("Chart validation failed")
    assert "donut" in result


def test_empty_data_fails(chart_tools):
    result = chart_tools.create_chart(chart_type="bar", data=[], config={"a": "A"}, x_key="a")
    assert result.startswith("Chart validation failed")
    assert "non-empty" in result


def test_empty_config_fails(chart_tools):
    result = chart_tools.create_chart(chart_type="bar", data=[{"a": "x", "b": 1}], config={}, x_key="a")
    assert result.startswith("Chart validation failed")
    assert "config" in result


def test_config_key_missing_from_data_fails(chart_tools):
    result = chart_tools.create_chart(
        chart_type="bar",
        data=[{"month": "Jan", "revenue": 1}],
        config={"other": "Other"},
        x_key="month",
    )
    assert result.startswith("Chart validation failed")
    assert "other" in result


def test_cartesian_without_x_key_fails(chart_tools):
    result = chart_tools.create_chart(
        chart_type="line",
        data=[{"month": "Jan", "runs": 1}],
        config={"runs": "Runs"},
    )
    assert result.startswith("Chart validation failed")
    assert "x_key" in result


def test_x_key_missing_from_rows_fails(chart_tools):
    result = chart_tools.create_chart(
        chart_type="bar",
        data=[{"month": "Jan", "runs": 1}, {"runs": 2}],
        config={"runs": "Runs"},
        x_key="month",
    )
    assert result.startswith("Chart validation failed")
    assert "month" in result


def test_non_numeric_series_value_fails(chart_tools):
    result = chart_tools.create_chart(
        chart_type="line",
        data=[{"day": "Mon", "runs": "abc"}],
        config={"runs": "Runs"},
        x_key="day",
    )
    assert result.startswith("Chart validation failed")
    assert "numeric" in result


def test_nested_row_value_fails(chart_tools):
    result = chart_tools.create_chart(
        chart_type="bar",
        data=[{"month": "Jan", "revenue": {"amount": 1}}],
        config={"revenue": "Revenue"},
        x_key="month",
    )
    assert result.startswith("Chart validation failed")
    assert "flat" in result


def test_pie_without_keys_fails(chart_tools):
    result = chart_tools.create_chart(
        chart_type="pie",
        data=[{"provider": "openai", "runs": 1}],
        config={"runs": "Runs"},
    )
    assert result.startswith("Chart validation failed")
    assert "name_key" in result


def test_pie_value_key_without_config_label_fails(chart_tools):
    result = chart_tools.create_chart(
        chart_type="pie",
        data=[{"provider": "openai", "runs": 1}],
        config={"provider": "Provider"},
        name_key="provider",
        value_key="runs",
    )
    assert result.startswith("Chart validation failed")
    assert "runs" in result


def test_chart_block_json_is_valid(chart_tools):
    """The fenced block must contain valid standalone JSON for the frontend parser."""
    result = chart_tools.create_chart(
        chart_type="bar",
        data=[{"month": "Jan", "revenue": 1}],
        config={"revenue": "Revenue"},
        x_key="month",
    )
    payload = result.removeprefix("```chart\n").removesuffix("\n```")
    parsed = json.loads(payload)
    assert isinstance(parsed, dict)
