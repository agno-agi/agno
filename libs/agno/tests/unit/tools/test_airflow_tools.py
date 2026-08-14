import json
import tempfile
from pathlib import Path

from agno.tools.airflow import AirflowTools


def test_save_and_read_dag_file_basic():
    with tempfile.TemporaryDirectory() as tmp_dir:
        dags_dir = Path(tmp_dir)
        airflow_tools = AirflowTools(dags_dir=dags_dir)

        contents = "from airflow import DAG\n"
        result = json.loads(airflow_tools.save_dag_file(contents=contents, dag_file="nested/example.py"))

        expected_path = dags_dir / "nested" / "example.py"
        assert result == {"file_path": str(expected_path.resolve())}
        assert expected_path.read_text() == contents
        assert json.loads(airflow_tools.read_dag_file("nested/example.py")) == {"contents": contents}


def test_save_dag_file_not_registered_by_default():
    """save_dag_file is opt-in (writes files to disk)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        airflow_tools = AirflowTools(dags_dir=tmp_dir)
        assert "save_dag_file" not in airflow_tools.functions
        assert "read_dag_file" in airflow_tools.functions


def test_save_dag_file_registered_when_opted_in():
    with tempfile.TemporaryDirectory() as tmp_dir:
        airflow_tools = AirflowTools(dags_dir=tmp_dir, save_dag_file=True)
        assert "save_dag_file" in airflow_tools.functions


def test_save_dag_file_rejects_absolute_path():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        dags_dir = base_dir / "dags"
        outside_file = base_dir / "outside.py"
        airflow_tools = AirflowTools(dags_dir=dags_dir)

        result = json.loads(airflow_tools.save_dag_file(contents="malicious", dag_file=str(outside_file)))

        assert "Path security error" in result["error"]
        assert not outside_file.exists()


def test_save_dag_file_rejects_traversal():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        dags_dir = base_dir / "dags"
        outside_file = base_dir / "outside.py"
        airflow_tools = AirflowTools(dags_dir=dags_dir)

        result = json.loads(airflow_tools.save_dag_file(contents="malicious", dag_file="../outside.py"))

        assert "Path security error" in result["error"]
        assert not outside_file.exists()


def test_read_dag_file_rejects_absolute_path():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        dags_dir = base_dir / "dags"
        outside_file = base_dir / "outside.py"
        outside_file.write_text("secret")
        airflow_tools = AirflowTools(dags_dir=dags_dir)

        result = json.loads(airflow_tools.read_dag_file(str(outside_file)))

        assert "Path security error" in result["error"]
        assert "secret" not in result["error"]


def test_read_dag_file_rejects_traversal():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        dags_dir = base_dir / "dags"
        outside_file = base_dir / "outside.py"
        outside_file.write_text("secret")
        airflow_tools = AirflowTools(dags_dir=dags_dir)

        result = json.loads(airflow_tools.read_dag_file("../outside.py"))

        assert "Path security error" in result["error"]
        assert "secret" not in result["error"]


def test_dags_dir_resolved():
    with tempfile.TemporaryDirectory() as tmp_dir:
        dags_dir = Path(tmp_dir) / "dags" / ".." / "dags"

        airflow_tools = AirflowTools(dags_dir=dags_dir)

        assert airflow_tools.dags_dir == dags_dir.resolve()
        assert airflow_tools.dags_dir.is_absolute()
