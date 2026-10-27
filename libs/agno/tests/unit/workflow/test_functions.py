"""Deterministic workflow transformations preserve content, errors and artifacts."""

import csv
import io
import json

import pytest
from pydantic import BaseModel

from agno.workflow import functions
from agno.workflow.types import StepInput, StepOutput


def test_extract_json_ignores_small_citations_and_uses_largest_payload():
    content = '[1] Sources\n```json\n{"rows": [{"name": "Ada", "score": 3}]}\n```\n[2]'
    assert json.loads(functions.extract_json(StepInput(previous_step_content=content))) == {
        "rows": [{"name": "Ada", "score": 3}]
    }


def test_extract_json_preserves_structured_input_and_previous_step_precedence():
    class Payload(BaseModel):
        label: str

    step = StepInput(input='{"ignored": true}', previous_step_content=Payload(label="café"))
    assert json.loads(functions.extract_json(step)) == {"label": "café"}
    assert json.loads(functions.extract_json(StepInput(input={"input": True}))) == {"input": True}


@pytest.mark.parametrize("content", ["", "not JSON", "{broken", "42", "null"])
def test_extract_json_reports_missing_object_or_array(content):
    assert functions.extract_json(StepInput(previous_step_content=content)).startswith("Error: ")


def test_extract_urls_deduplicates_in_order_and_removes_sentence_punctuation():
    step = StepInput(input="See https://example.com/a. Then https://example.org/b! Again https://example.com/a")
    assert functions.extract_urls(step) == "https://example.com/a\nhttps://example.org/b"


def test_csv_columns_nested_values_and_artifact_content():
    rows = [{"name": "café", "details": {"a": 1}}, {"name": "Ada", "count": 2}]
    output = functions.json_to_csv(StepInput(previous_step_content={"rows": rows}))
    parsed = list(csv.DictReader(io.StringIO(output.content)))
    assert list(parsed[0]) == ["name", "details", "count"]
    assert parsed == [
        {"name": "café", "details": '{"a": 1}', "count": ""},
        {"name": "Ada", "details": "", "count": "2"},
    ]
    assert output.files[0].filename == "data.csv"
    assert output.files[0].mime_type == "text/csv"
    assert output.files[0].content.decode() == output.content


@pytest.mark.parametrize("value", [[], [1], {"a": [], "b": []}, "missing"])
def test_csv_rejects_non_tabular_data(value):
    output = functions.json_to_csv(StepInput(previous_step_content=value))
    assert output.content.startswith("Error: ")
    assert not output.files


def test_markdown_escapes_cells_and_caps_rows():
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["name", "detail"])
    writer.writerow(["a|b", "line1\nline2"])
    writer.writerows([[str(i), "x"] for i in range(51)])
    output = functions.csv_to_markdown_table(StepInput(input=buffer.getvalue()))
    assert "a\\|b" in output
    assert "line1<br>line2" in output
    assert output.endswith("... 2 more rows")
    assert len(output.splitlines()) == 53


def test_package_content_preserves_utf8_and_flows_to_next_step():
    output = functions.content_to_file(StepInput(previous_step_content="# café\n"))
    assert output.content == "# café\n"
    assert output.files[0].content == "# café\n".encode()
    assert output.files[0].filename == "output.md"
    assert output.files[0].mime_type == "text/markdown"


@pytest.mark.parametrize(
    "name", ["extract_json", "extract_urls", "json_to_csv", "csv_to_markdown_table", "content_to_file"]
)
async def test_error_propagation_and_async_parity(name):
    step = StepInput(previous_step_content="Error: upstream failed")
    sync = getattr(functions, name)(step)
    asynchronous = await getattr(functions, "a" + name)(step)
    if isinstance(sync, StepOutput):
        assert sync.content == asynchronous.content == "Error: upstream failed"
        assert not sync.files and not asynchronous.files
    else:
        assert sync == asynchronous == "Error: upstream failed"


@pytest.mark.parametrize(
    "name,content",
    [
        ("extract_json", '[{"ok": true}]'),
        ("extract_urls", "https://example.org"),
        ("json_to_csv", '[{"ok": true}]'),
        ("csv_to_markdown_table", "name\nAda\n"),
        ("content_to_file", "hello"),
    ],
)
async def test_async_success_parity(name, content):
    step = StepInput(input=content)
    sync = getattr(functions, name)(step)
    asynchronous = await getattr(functions, "a" + name)(step)
    if isinstance(sync, StepOutput):
        assert sync.content == asynchronous.content
        assert [(f.content, f.filename, f.mime_type) for f in sync.files] == [
            (f.content, f.filename, f.mime_type) for f in asynchronous.files
        ]
    else:
        assert sync == asynchronous


@pytest.mark.parametrize(
    "content", ['column\n"unterminated', "column\n" + "x" * 131073], ids=["malformed", "oversized"]
)
@pytest.mark.parametrize("use_async", [False, True])
def test_csv_parse_failures_follow_the_error_content_contract(content, use_async):
    import asyncio

    step = StepInput(previous_step_content=content)
    result = asyncio.run(functions.acsv_to_markdown_table(step)) if use_async else functions.csv_to_markdown_table(step)
    assert result.startswith("Error: ")
    assert functions.content_to_file(StepInput(previous_step_content=result)).files is None


def test_csv_reports_errors_even_after_the_display_row_cap():
    content = "column\n" + "value\n" * 51 + '"unterminated'
    assert functions.csv_to_markdown_table(StepInput(previous_step_content=content)).startswith("Error: ")
