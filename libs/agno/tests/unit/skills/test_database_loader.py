"""Unit tests for DatabaseSkills loader."""

from typing import Dict, List
from unittest.mock import Mock, patch

import pytest

from agno.skills.errors import SkillParseError
from agno.skills.loaders.database import DatabaseSkills
from agno.skills.skill import Skill


class MockDBSkill:
    """Mock skill row from database."""

    def __init__(self, data: Dict[str, any]):
        self.data = data

    def __getitem__(self, key: str) -> any:
        return self.data[key]

    def get(self, key: str, default: any = None) -> any:
        return self.data.get(key, default)


class MockCursor:
    """Mock database cursor for testing."""

    def __init__(self):
        self.skills_data: List[Dict] = []
        self.scripts_data: Dict[int, List[Dict]] = {}
        self.references_data: Dict[int, List[Dict]] = {}
        self.execute_calls: List[tuple] = []

    def execute(self, query: str, params: tuple = None):
        self.execute_calls.append((query, params))
        return self

    def fetchall(self) -> List[MockDBSkill]:
        """Return mock data based on the query."""
        if "skills" in self.execute_calls[-1][0] and "scripts" not in self.execute_calls[-1][0]:
            return [MockDBSkill(d) for d in self.skills_data]

        if "scripts" in self.execute_calls[-1][0]:
            skill_id = self.execute_calls[-1][1][0] if self.execute_calls[-1][1] else None
            return [MockDBSkill(d) for d in self.scripts_data.get(skill_id or 0, [])]

        if "references" in self.execute_calls[-1][0]:
            skill_id = self.execute_calls[-1][1][0] if self.execute_calls[-1][1] else None
            return [MockDBSkill(d) for d in self.references_data.get(skill_id or 0, [])]

        return []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class MockConnection:
    """Mock database connection for testing."""

    def __init__(self):
        self.cursor_obj = MockCursor()

    def cursor(self, cursor_factory=None):
        return self.cursor_obj

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


@pytest.fixture
def mock_db_connection():
    """Create a mock database connection with test data."""
    conn = MockConnection()

    # Setup test skills
    conn.cursor_obj.skills_data = [
        {
            "id": 1,
            "name": "test-skill",
            "description": "A test skill from database",
            "instructions": "# Test Instructions\n\nThis is from database.",
            "metadata": '{"version": "1.0", "author": "test"}',
            "license": "MIT",
            "compatibility": ">=1.0.0",
            "allowed_tools": ["tool1", "tool2"],
        },
        {
            "id": 2,
            "name": "minimal-skill",
            "description": "A minimal skill",
            "instructions": "---\nname: minimal-skill\n---\n\nMinimal instructions body.",
            "metadata": None,
            "license": None,
            "compatibility": None,
            "allowed_tools": None,
        },
    ]

    # Setup scripts for skills
    conn.cursor_obj.scripts_data = {
        1: [
            {"file_name": "helper.py"},
            {"file_name": "runner.sh"},
        ],
        2: [],
    }

    # Setup references for skills
    conn.cursor_obj.references_data = {
        1: [
            {"file_name": "guide.md"},
        ],
        2: [],
    }

    return conn


def test_database_skills_loads_from_db(mock_db_connection):
    """Test that DatabaseSkills loads skills from the database."""
    with patch("psycopg2.connect", return_value=mock_db_connection):
        loader = DatabaseSkills(conn_str="postgresql://user:pass@localhost/db")
        skills = loader.load()

        assert len(skills) == 2
        assert skills[0].name == "test-skill"
        assert skills[0].description == "A test skill from database"
        assert "# Test Instructions" in skills[0].instructions


def test_database_skills_with_scripts_and_references(mock_db_connection):
    """Test that scripts and references are loaded correctly."""
    with patch("psycopg2.connect", return_value=mock_db_connection):
        loader = DatabaseSkills(conn_str="postgresql://user:pass@localhost/db")
        skills = loader.load()

        test_skill = next(s for s in skills if s.name == "test-skill")
        assert test_skill.scripts == ["helper.py", "runner.sh"]
        assert test_skill.references == ["guide.md"]


def test_database_skills_parses_metadata(mock_db_connection):
    """Test that metadata JSON is parsed correctly."""
    with patch("psycopg2.connect", return_value=mock_db_connection):
        loader = DatabaseSkills(conn_str="postgresql://user:pass@localhost/db")
        skills = loader.load()

        test_skill = next(s for s in skills if s.name == "test-skill")
        assert test_skill.metadata is not None
        assert test_skill.metadata["version"] == "1.0"
        assert test_skill.metadata["author"] == "test"


def test_database_skills_parses_frontmatter():
    """Test that YAML frontmatter in instructions is stripped."""
    with patch("psycopg2.connect", return_value=MockConnection()):
        loader = DatabaseSkills(conn_str="postgresql://user:pass@localhost/db")

        skill_data = {
            "id": 1,
            "name": "frontmatter-skill",
            "description": "Skill with frontmatter",
            "instructions": "---\nname: test\n---\n\nBody after frontmatter",
            "metadata": None,
            "license": None,
            "compatibility": None,
            "allowed_tools": None,
        }
        scripts = []
        references = []

        skill = loader._create_skill(skill_data, scripts, references)
        assert skill is not None
        assert "Body after frontmatter" in skill.instructions
        assert "---" not in skill.instructions


def test_database_skills_handles_empty_scripts_references():
    """Test skills with no scripts or references."""
    with patch("psycopg2.connect", return_value=MockConnection()):
        loader = DatabaseSkills(conn_str="postgresql://user:pass@localhost/db")

        skill_data = {
            "id": 1,
            "name": "empty-skill",
            "description": "Skill with nothing",
            "instructions": "Just instructions",
            "metadata": None,
            "license": None,
            "compatibility": None,
            "allowed_tools": None,
        }
        scripts = []
        references = []

        skill = loader._create_skill(skill_data, scripts, references)
        assert skill is not None
        assert skill.scripts == []
        assert skill.references == []


def test_database_skills_parses_allowed_tools_array():
    """Test that allowed_tools array is parsed correctly."""
    with patch("psycopg2.connect", return_value=MockConnection()):
        loader = DatabaseSkills(conn_str="postgresql://user:pass@localhost/db")

        skill_data = {
            "id": 1,
            "name": "tools-skill",
            "description": "Skill with tools",
            "instructions": "Instructions",
            "metadata": None,
            "license": None,
            "compatibility": None,
            "allowed_tools": '["tool1", "tool2", "tool3"]',
        }
        scripts = []
        references = []

        skill = loader._create_skill(skill_data, scripts, references)
        assert skill.allowed_tools == ["tool1", "tool2", "tool3"]


def test_database_skills_with_table_prefix(mock_db_connection):
    """Test loader with custom table prefix."""
    with patch("psycopg2.connect", return_value=mock_db_connection):
        loader = DatabaseSkills(
            conn_str="postgresql://user:pass@localhost/db",
            table_prefix="agno_",
        )
        skills = loader.load()

        # Verify that queries use prefixed table names
        execute_calls = mock_db_connection.cursor_obj.execute_calls
        queries = [call[0] for call in execute_calls]
        for query in queries:
            if "skills" in query:
                assert "agno_skills" in query


def test_database_skills_connection_error():
    """Test that connection errors are handled properly."""
    with patch("psycopg2.connect") as mock_connect:
        mock_connect.side_effect = Exception("Connection failed")

        loader = DatabaseSkills(conn_str="postgresql://user:pass@localhost/db")
        with pytest.raises(Exception, match="Connection failed"):
            loader.load()


def test_database_skills_psycopg2_not_installed():
    """Test that ImportError is raised when psycopg2 is not installed."""
    with patch.dict("sys.modules", {"psycopg2": None}):
        # Force reimport to trigger the ImportError
        import importlib
        import sys

        if "agno.skills.loaders.database" in sys.modules:
            del sys.modules["agno.skills.loaders.database"]

        with pytest.raises(ImportError):
            from agno.skills.loaders.database import DatabaseSkills

            loader = DatabaseSkills(conn_str="postgresql://user:pass@localhost/db")
            loader.load()
