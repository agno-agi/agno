import json
from typing import Any, Dict, List, Optional, Tuple

from agno.db.migrations.versions.v2_3_0 import _async_convert_json_to_jsonb, _convert_json_to_jsonb


class _Result:
    def __init__(self, scalar: Any = None, rows: Optional[List[Tuple[str, str]]] = None) -> None:
        self._scalar = scalar
        self._rows = rows or []

    def scalar(self) -> Any:
        return self._scalar

    def fetchall(self) -> List[Tuple[str, str]]:
        return self._rows


class _Session:
    """Answers the column-type lookup and the NUL-row query, and records every statement."""

    def __init__(self, column_types: Dict[str, str], nul_rows: Optional[Dict[str, List[Tuple[str, str]]]] = None):
        self.column_types = column_types
        self.nul_rows = nul_rows or {}
        self.statements: List[Tuple[str, Optional[Dict[str, Any]]]] = []

    def execute(self, statement: Any, params: Optional[Dict[str, Any]] = None) -> _Result:
        sql = " ".join(str(statement).split())
        self.statements.append((sql, params))
        if "information_schema.columns" in sql:
            return _Result(scalar=self.column_types.get(params["column_name"]))  # type: ignore[index]
        if sql.startswith("SELECT ctid"):
            column = sql.split("SELECT ctid::text, ")[1].split("::text")[0]
            return _Result(rows=self.nul_rows.get(column, []))
        return _Result()

    def sql(self, prefix: str) -> List[str]:
        return [sql for sql, _ in self.statements if sql.startswith(prefix)]


class _AsyncSession(_Session):
    async def execute(self, statement: Any, params: Optional[Dict[str, Any]] = None) -> _Result:  # type: ignore[override]
        return _Session.execute(self, statement, params)


SESSION_COLUMNS = [
    ("session_data", "sessions"),
    ("runs", "sessions"),
    ("summary", "sessions"),
    ("metadata", "sessions"),
]


def test_all_json_columns_of_a_table_convert_in_one_alter():
    sess = _Session({"session_data": "json", "runs": "json", "summary": "json", "metadata": "jsonb"})

    _convert_json_to_jsonb(sess, "ai", SESSION_COLUMNS)

    assert sess.sql("ALTER TABLE") == [
        'ALTER TABLE "ai"."sessions" ALTER COLUMN session_data TYPE JSONB USING session_data::jsonb, '
        "ALTER COLUMN runs TYPE JSONB USING runs::jsonb, ALTER COLUMN summary TYPE JSONB USING summary::jsonb"
    ]


def test_nothing_is_altered_when_no_column_is_json():
    sess = _Session({"session_data": "jsonb", "runs": "jsonb", "summary": "jsonb", "metadata": "jsonb"})

    _convert_json_to_jsonb(sess, "ai", SESSION_COLUMNS)

    assert sess.sql("ALTER TABLE") == []
    assert sess.sql("SELECT ctid") == []


def test_a_nul_escape_is_removed_before_the_alter():
    stored = json.dumps([{"run_id": "r1", "content": "tool output with a \x00 byte"}])
    sess = _Session({"runs": "json"}, nul_rows={"runs": [("(0,7)", stored)]})

    _convert_json_to_jsonb(sess, "ai", [("runs", "sessions")])

    updates = [(sql, params) for sql, params in sess.statements if sql.startswith("UPDATE")]
    assert updates == [
        (
            'UPDATE "ai"."sessions" SET runs = CAST(:value AS json) WHERE ctid = CAST(:ctid AS tid)',
            {"ctid": "(0,7)", "value": json.dumps([{"run_id": "r1", "content": "tool output with a  byte"}])},
        )
    ]
    order = [sql.split()[0] for sql, _ in sess.statements if sql.split()[0] in ("UPDATE", "ALTER")]
    assert order == ["UPDATE", "ALTER"]


async def test_async_converts_in_one_alter_and_removes_a_nul_escape():
    stored = json.dumps({"note": "a\x00b"})
    sess = _AsyncSession({"session_data": "json", "runs": "json"}, nul_rows={"session_data": [("(1,2)", stored)]})

    await _async_convert_json_to_jsonb(sess, "ai", [("session_data", "sessions"), ("runs", "sessions")])

    assert sess.sql("ALTER TABLE") == [
        'ALTER TABLE "ai"."sessions" ALTER COLUMN session_data TYPE JSONB USING session_data::jsonb, '
        "ALTER COLUMN runs TYPE JSONB USING runs::jsonb"
    ]
    assert [params for sql, params in sess.statements if sql.startswith("UPDATE")] == [
        {"ctid": "(1,2)", "value": json.dumps({"note": "ab"})}
    ]
