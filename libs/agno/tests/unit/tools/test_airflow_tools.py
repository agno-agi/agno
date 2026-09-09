import tempfile
from pathlib import Path

from agno.tools.airflow import AirflowTools


def test_save_and_read_dag_file_basic():
    with tempfile.TemporaryDirectory() as tmp_dir:
        dags_dir = Path(tmp_dir)
        airflow_tools = AirflowTools(dags_dir=dags_dir)

        contents = "from airflow import DAG\n"
        result = airflow_tools.save_dag_file(contents=contents, dag_file="nested/example.py")

        expected_path = dags_dir / "nested" / "example.py"
        assert result == str(expected_path.resolve())
        assert expected_path.read_text() == contents
        assert airflow_tools.read_dag_file("nested/example.py") == contents


def test_save_dag_file_rejects_absolute_path():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        dags_dir = base_dir / "dags"
        outside_file = base_dir / "outside.py"
        airflow_tools = AirflowTools(dags_dir=dags_dir)

        result = airflow_tools.save_dag_file(contents="malicious", dag_file=str(outside_file))

        assert result.startswith("Error saving to file:")
        assert not outside_file.exists()


def test_save_dag_file_rejects_traversal():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        dags_dir = base_dir / "dags"
        outside_file = base_dir / "outside.py"
        airflow_tools = AirflowTools(dags_dir=dags_dir)

        result = airflow_tools.save_dag_file(contents="malicious", dag_file="../outside.py")

        assert result.startswith("Error saving to file:")
        assert not outside_file.exists()


def test_read_dag_file_rejects_absolute_path():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        dags_dir = base_dir / "dags"
        outside_file = base_dir / "outside.py"
        outside_file.write_text("secret")
        airflow_tools = AirflowTools(dags_dir=dags_dir)

        result = airflow_tools.read_dag_file(str(outside_file))

        assert result.startswith("Error reading file:")
        assert "secret" not in result


def test_read_dag_file_rejects_traversal():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        dags_dir = base_dir / "dags"
        outside_file = base_dir / "outside.py"
        outside_file.write_text("secret")
        airflow_tools = AirflowTools(dags_dir=dags_dir)

        result = airflow_tools.read_dag_file("../outside.py")

        assert result.startswith("Error reading file:")
        assert "secret" not in result


def test_dags_dir_resolved():
    with tempfile.TemporaryDirectory() as tmp_dir:
        dags_dir = Path(tmp_dir) / "dags" / ".." / "dags"

        airflow_tools = AirflowTools(dags_dir=dags_dir)

        assert airflow_tools.dags_dir == dags_dir.resolve()
        assert airflow_tools.dags_dir.is_absolute()
