"""Run-preview projection shared by the SQLAlchemy backends (SQLite, Postgres, MySQL)."""

from typing import Any, Dict, List

from sqlalchemy import Table, case

from agno.db.utils import RUN_PREVIEW_FIELDS


def run_preview_columns(runs_table: Table) -> List[Any]:
    """The preview keys read out of ``run_data`` by the dialect's JSON operators, not the whole blob."""
    data = runs_table.c.run_data
    input_content = data[("input", "input_content")]
    return [
        *(data[key].label(key) for key in RUN_PREVIEW_FIELDS if key != "input"),
        input_content.label("input_content"),
        # Workflow runs preview their raw input; other runs read only input_content, leaving media behind.
        case((data["workflow_id"].as_string().is_not(None), data["input"])).label("workflow_input"),
        # What the input preview falls back to, read only for runs that stored no input to preview.
        case((input_content.as_string().is_(None), data["messages"])).label("messages"),
        case((data["input"].as_string().is_(None), data["step_executor_runs"])).label("step_executor_runs"),
    ]


def run_preview_from_row(row: Any) -> Dict[str, Any]:
    values = dict(row._mapping)
    workflow_input, input_content = values.pop("workflow_input"), values.pop("input_content")
    # Stored runs never hold None values, so a NULL read is an absent key.
    run = {key: value for key, value in values.items() if value is not None}
    if workflow_input is not None:
        run["input"] = workflow_input
    elif input_content is not None:
        run["input"] = {"input_content": input_content}
    return run
