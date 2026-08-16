"""Every operationId served by a mounted AgentOS app must be unique.

Duplicate operationIds make the emitted OpenAPI document invalid and cause
SDK generators to overwrite or mangle one of the colliding methods.
"""

from collections import Counter

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS


def test_served_operation_ids_are_unique(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "ops.db"))
    app = AgentOS(agents=[Agent(name="op-probe", db=db)], db=db).get_app()
    spec = app.openapi()
    ids = [
        operation["operationId"]
        for methods in spec["paths"].values()
        for operation in methods.values()
        if isinstance(operation, dict) and operation.get("operationId")
    ]
    duplicates = {op_id: count for op_id, count in Counter(ids).items() if count > 1}
    assert duplicates == {}, f"duplicate operationIds break OpenAPI client generation: {duplicates}"
