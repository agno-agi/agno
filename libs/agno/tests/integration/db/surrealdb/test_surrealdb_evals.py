# Run SurrealDB in a container before running this script
#
# ```
# docker run --rm --pull always -p 8000:8000 surrealdb/surrealdb:latest start --user root --pass root
# ```
#
# or with
#
# ```
# surreal start -u root -p root
# ```
#
# Then, run this test like this:
#
# ```
# pytest libs/agno/tests/integration/db/surrealdb/test_surrealdb_evals.py
# ```

import pytest

from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.db.surrealdb import SurrealDb
from agno.debug import enable_debug_mode

enable_debug_mode()

# SurrealDB connection parameters
SURREALDB_URL = "ws://localhost:8000"
SURREALDB_USER = "root"
SURREALDB_PASSWORD = "root"
SURREALDB_NAMESPACE = "test"
SURREALDB_DATABASE = "test"


@pytest.fixture
def db() -> SurrealDb:
    """Create a SurrealDB memory database for testing."""
    creds = {"username": SURREALDB_USER, "password": SURREALDB_PASSWORD}
    db = SurrealDb(None, SURREALDB_URL, creds, SURREALDB_NAMESPACE, SURREALDB_DATABASE)
    return db


def test_crud_evals(db: SurrealDb):
    db.clear_evals()
    new_eval = EvalRunRecord(run_id="1", agent_id="1", eval_type=EvalType.ACCURACY, eval_data={"foo": 42})
    new_eval_2 = EvalRunRecord(run_id="2", agent_id="2", eval_type=EvalType.ACCURACY, eval_data={"bar": 67})

    # create
    eval_created = db.create_eval_run(new_eval)
    eval_created_2 = db.create_eval_run(new_eval_2)
    assert eval_created is not None
    assert eval_created_2 is not None
    assert eval_created.run_id == new_eval.run_id
    assert eval_created_2.run_id == new_eval_2.run_id

    # get
    eval_returned = db.get_eval_run(new_eval.run_id)
    assert isinstance(eval_returned, EvalRunRecord)
    assert eval_returned.run_id == new_eval.run_id
    assert eval_returned.agent_id == "1"

    eval_returned = db.get_eval_run(new_eval.run_id, False)
    assert isinstance(eval_returned, dict)
    assert eval_returned["run_id"] == new_eval.run_id
    assert eval_returned["agent_id"] == "1"

    # rename
    renamed = db.rename_eval_run(new_eval.run_id, "new name")
    assert isinstance(renamed, EvalRunRecord)
    assert renamed.name == "new name"

    # get multiple
    # TODO: test filters
    evals = db.get_eval_runs()
    assert len(evals) == 2
    evals = db.get_eval_runs(filter_type=EvalFilterType.AGENT, agent_id="1")
    assert len(evals) == 1

    # delete
    eval_ids = [new_eval.run_id, new_eval_2.run_id]
    db.delete_eval_runs(eval_ids)
