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
# pytest libs/agno/tests/integration/db/surrealdb/test_surrealdb_metrics.py
# ```


import pytest

from agno.db.schemas.evals import EvalRunRecord, EvalType
from agno.db.surrealdb import SurrealDb
from agno.debug import enable_debug_mode
from agno.session.agent import AgentSession

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


def test_calculate_metrics(db: SurrealDb):
    db.clear_sessions()
    db.clear_evals()

    new_eval = EvalRunRecord(run_id="1", agent_id="1", eval_type=EvalType.ACCURACY, eval_data={"foo": 42})

    sess = AgentSession(session_id="1", agent_id="1")
    # sleep(1)
    sess2 = AgentSession(session_id="2", agent_id="2")

    # upsert
    db.upsert_sessions([sess, sess2])
    _ = db.create_eval_run(new_eval)

    # metrics
    db.calculate_metrics()

    metrics, last = db.get_metrics()
    print(metrics)
    print(last)
