import pytest

from agno.agent import Agent
from agno.db.postgres.postgres import PostgresDb
from agno.db.sqlite.sqlite import SqliteDb
from agno.os import AgentOS


def test_equal_db_instances_with_same_configuration_are_compatible():
    """Test that different db instances with the same id are not compatible"""
    # Two db instances with the same id and configuration
    db1 = PostgresDb(db_url="postgresql://localhost:5432/test", id="test")
    db2 = PostgresDb(db_url="postgresql://localhost:5432/test", id="test")
    assert db1 != db2
    assert db1.id == db2.id

    agent1 = Agent(db=db1)
    agent2 = Agent(db=db2)
    agent_os = AgentOS(agents=[agent1, agent2])

    # Asserting the app gets created without raising
    app = agent_os.get_app()
    assert app is not None


def test_db_instances_with_different_url_are_not_compatible():
    """Test that different db instances with the same id and different url are not compatible"""
    # Two db instances with the same id and different url
    db1 = PostgresDb(db_url="postgresql://localhost:5432/test", id="test")
    db2 = PostgresDb(db_url="postgresql://localhost:5433/test", id="test")
    assert db1.id == db2.id
    assert db1.db_url != db2.db_url

    agent1 = Agent(db=db1)
    agent2 = Agent(db=db2)
    agent_os = AgentOS(agents=[agent1, agent2])

    # Asserting an error is raised when trying to create the app containing incompatible databases
    with pytest.raises(ValueError) as e:
        agent_os.get_app()

    assert "Database ID conflict detected" in str(e.value)


def test_db_instances_with_different_db_files_are_not_compatible():
    """Test that different db instances with the same id and different db files are not compatible"""
    # Two db instances with the same id and different db files
    db1 = SqliteDb(db_file="tmp/test.db", id="test")
    db2 = SqliteDb(db_file="tmp/test2.db", id="test")
    assert db1.id == db2.id
    assert db1.db_file != db2.db_file

    agent1 = Agent(db=db1)
    agent2 = Agent(db=db2)
    agent_os = AgentOS(agents=[agent1, agent2])

    # Asserting an error is raised when trying to create the app containing incompatible databases
    with pytest.raises(ValueError) as e:
        agent_os.get_app()

    assert "Database ID conflict detected" in str(e.value)


def test_db_instances_with_different_table_names_are_not_compatible():
    """Test that different db instances with the same id and different table names are not compatible"""
    # Two db instances with the same id and different table names
    db1 = PostgresDb(db_url="postgresql://localhost:5432/test", id="test", session_table="sessions")
    db2 = PostgresDb(db_url="postgresql://localhost:5433/test", id="test", session_table="sessions2")
    assert db1.id == db2.id
    assert db1.session_table_name != db2.session_table_name

    agent1 = Agent(db=db1)
    agent2 = Agent(db=db2)
    agent_os = AgentOS(agents=[agent1, agent2])

    # Asserting an error is raised when trying to create the app containing incompatible databases
    with pytest.raises(ValueError) as e:
        agent_os.get_app()

    assert "Database ID conflict detected" in str(e.value)
