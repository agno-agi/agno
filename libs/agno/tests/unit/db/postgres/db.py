import pytest
from unittest.mock import Mock, patch, MagicMock, call
from datetime import datetime, timezone, date
from uuid import uuid4

from sqlalchemy import create_engine, Column, String, DateTime, Boolean, Integer, JSON, BigInteger, Date, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import MetaData, Table, Index, UniqueConstraint
from sqlalchemy.exc import SQLAlchemyError

# Import from the actual module structure
from agno.db.postgres.postgres import PostgresDb
from agno.db.postgres.schemas import (
    get_table_schema_definition,
    SESSION_TABLE_SCHEMA,
    MEMORY_TABLE_SCHEMA,
    EVAL_TABLE_SCHEMA,
    KNOWLEDGE_TABLE_SCHEMA,
    METRICS_TABLE_SCHEMA
)


class TestPostgresDb:
    """Test suite for PostgresDb class"""

    @pytest.fixture
    def mock_engine(self):
        """Create a mock SQLAlchemy engine"""
        engine = Mock(spec=Engine)
        return engine

    @pytest.fixture
    def mock_session(self):
        """Create a mock session"""
        session = Mock(spec=Session)
        session.__enter__ = Mock(return_value=session)
        session.__exit__ = Mock(return_value=None)
        session.begin = Mock()
        session.begin().__enter__ = Mock(return_value=session)
        session.begin().__exit__ = Mock(return_value=None)
        return session

    @pytest.fixture
    def postgres_db(self, mock_engine):
        """Create a PostgresDb instance with mock engine"""
        return PostgresDb(
            db_engine=mock_engine,
            db_schema="test_schema",
            session_table="test_sessions",
            memory_table="test_memories",
            metrics_table="test_metrics",
            eval_table="test_evals",
            knowledge_table="test_knowledge"
        )

    def test_init_with_engine(self, mock_engine):
        """Test initialization with engine"""
        db = PostgresDb(
            db_engine=mock_engine,
            session_table="sessions"
        )
        assert db.db_engine == mock_engine
        assert db.db_schema == "ai"  # default schema
        assert db.session_table_name == "sessions"

    @patch('agno.db.postgres.postgres.create_engine')
    def test_init_with_url(self, mock_create_engine):
        """Test initialization with database URL"""
        mock_engine = Mock(spec=Engine)
        mock_create_engine.return_value = mock_engine
        
        db = PostgresDb(
            db_url="postgresql://user:pass@localhost/db",
            session_table="sessions"
        )
        
        mock_create_engine.assert_called_once_with("postgresql://user:pass@localhost/db")
        assert db.db_engine == mock_engine

    def test_init_no_engine_or_url(self):
        """Test initialization fails without engine or URL"""
        with pytest.raises(ValueError, match="One of db_url or db_engine must be provided"):
            PostgresDb(session_table="sessions")

    def test_init_no_tables(self, mock_engine):
        """Test initialization fails without any tables"""
        # The validation happens in BaseDb, not PostgresDb
        # So we need to test that BaseDb raises the error
        with pytest.raises(ValueError, match="At least one table must be specified"):
            PostgresDb(db_engine=mock_engine)

    def test_create_table(self, postgres_db, mock_session):
        """Test table creation"""
        # Mock Session
        postgres_db.Session = Mock(return_value=mock_session)
        
        # Mock table creation
        with patch.object(Table, 'create') as mock_table_create:
            with patch('agno.db.postgres.postgres.create_schema') as mock_create_schema:
                table = postgres_db._create_table("test_sessions", "sessions", "test_schema")
        
        # Verify schema was created
        mock_create_schema.assert_called_once()
        
        # Verify table creation
        mock_table_create.assert_called_once_with(postgres_db.db_engine, checkfirst=True)
        
        # Verify table has correct structure
        assert table.name == "test_sessions"
        assert table.schema == "test_schema"
        
        # Verify columns exist
        column_names = [col.name for col in table.columns]
        expected_columns = ["session_id", "session_type", "agent_id", "team_id", 
                          "workflow_id", "user_id", "team_session_id", "session_data",
                          "agent_data", "team_data", "workflow_data", "extra_data",
                          "runs", "summary", "created_at", "updated_at"]
        for col in expected_columns:
            assert col in column_names

    def test_create_table_with_indexes(self, postgres_db, mock_session):
        """Test table creation with indexes"""
        postgres_db.Session = Mock(return_value=mock_session)
        mock_session.execute.return_value.scalar.return_value = None  # Index doesn't exist
        
        with patch.object(Table, 'create'):
            with patch.object(Index, 'create') as mock_index_create:
                with patch('agno.db.postgres.postgres.create_schema'):
                    table = postgres_db._create_table("test_metrics", "metrics", "test_schema")
        
        # Verify table has indexes on date and created_at columns
        indexed_columns = [col.name for col in table.columns if any(idx.contains_column(col) for idx in table.indexes)]
        assert "date" in indexed_columns
        assert "created_at" in indexed_columns

    def test_create_table_with_unique_constraints(self, postgres_db, mock_session):
        """Test table creation with unique constraints"""
        postgres_db.Session = Mock(return_value=mock_session)
        
        with patch.object(Table, 'create'):
            with patch('agno.db.postgres.postgres.create_schema'):
                table = postgres_db._create_table("test_metrics", "metrics", "test_schema")
        
        # Verify unique constraint was added
        constraint_names = [c.name for c in table.constraints if isinstance(c, UniqueConstraint)]
        assert "test_metrics_uq_metrics_date_period" in constraint_names
        
        # Verify the constraint has the correct columns
        for constraint in table.constraints:
            if isinstance(constraint, UniqueConstraint) and constraint.name == "test_metrics_uq_metrics_date_period":
                col_names = [col.name for col in constraint.columns]
                assert "date" in col_names
                assert "aggregation_period" in col_names

    def test_create_memory_table(self, postgres_db, mock_session):
        """Test creation of memory table with correct schema"""
        postgres_db.Session = Mock(return_value=mock_session)
        
        with patch.object(Table, 'create'):
            with patch('agno.db.postgres.postgres.create_schema'):
                table = postgres_db._create_table("test_memories", "memories", "test_schema")
        
        # Verify primary key
        pk_columns = [col.name for col in table.columns if col.primary_key]
        assert "memory_id" in pk_columns
        
        # Verify indexed columns
        indexed_columns = [col.name for col in table.columns if any(idx.contains_column(col) for idx in table.indexes)]
        assert "user_id" in indexed_columns
        assert "last_updated" in indexed_columns

    def test_create_eval_table(self, postgres_db, mock_session):
        """Test creation of eval table with correct schema"""
        postgres_db.Session = Mock(return_value=mock_session)
        
        with patch('agno.db.postgres.schemas.get_table_schema_definition') as mock_get_schema:
            mock_get_schema.return_value = EVAL_TABLE_SCHEMA.copy()
            
            with patch.object(Table, 'create'):
                table = postgres_db._create_table("test_evals", "evals", "test_schema")
            
            # Verify columns
            column_names = [col.name for col in table.columns]
            assert "run_id" in column_names
            assert "eval_type" in column_names
            assert "eval_data" in column_names
            
            # Verify primary key
            pk_columns = [col.name for col in table.columns if col.primary_key]
            assert "run_id" in pk_columns

    def test_create_knowledge_table(self, postgres_db, mock_session):
        """Test creation of knowledge table with correct schema"""
        postgres_db.Session = Mock(return_value=mock_session)
        
        with patch('agno.db.postgres.schemas.get_table_schema_definition') as mock_get_schema:
            mock_get_schema.return_value = KNOWLEDGE_TABLE_SCHEMA.copy()
            
            with patch.object(Table, 'create'):
                table = postgres_db._create_table("test_knowledge", "knowledge", "test_schema")
            
            # Verify columns
            column_names = [col.name for col in table.columns]
            expected_columns = ["id", "name", "description", "metadata", "type", 
                              "size", "linked_to", "access_count", "created_at", 
                              "updated_at", "status", "status_message"]
            for col in expected_columns:
                assert col in column_names

    def test_get_table_sessions(self, postgres_db):
        """Test getting sessions table"""
        mock_table = Mock(spec=Table)
        
        with patch.object(postgres_db, '_get_or_create_table', return_value=mock_table):
            table = postgres_db._get_table("sessions")
        
        assert table == mock_table
        assert hasattr(postgres_db, 'session_table')

    def test_get_table_memories(self, postgres_db):
        """Test getting memories table"""
        mock_table = Mock(spec=Table)
        
        with patch.object(postgres_db, '_get_or_create_table', return_value=mock_table):
            table = postgres_db._get_table("memories")
        
        assert table == mock_table
        assert hasattr(postgres_db, 'memory_table')

    def test_get_table_metrics(self, postgres_db):
        """Test getting metrics table"""
        mock_table = Mock(spec=Table)
        
        with patch.object(postgres_db, '_get_or_create_table', return_value=mock_table):
            table = postgres_db._get_table("metrics")
        
        assert table == mock_table
        assert hasattr(postgres_db, 'metrics_table')

    def test_get_table_evals(self, postgres_db):
        """Test getting evals table"""
        mock_table = Mock(spec=Table)
        
        with patch.object(postgres_db, '_get_or_create_table', return_value=mock_table):
            table = postgres_db._get_table("evals")
        
        assert table == mock_table
        assert hasattr(postgres_db, 'eval_table')

    def test_get_table_knowledge(self, postgres_db):
        """Test getting knowledge table"""
        mock_table = Mock(spec=Table)
        
        with patch.object(postgres_db, '_get_or_create_table', return_value=mock_table):
            table = postgres_db._get_table("knowledge")
        
        assert table == mock_table
        assert hasattr(postgres_db, 'knowledge_table')

    def test_get_table_invalid_type(self, postgres_db):
        """Test getting table with invalid type"""
        with pytest.raises(ValueError, match="Unknown table type"):
            postgres_db._get_table("invalid_type")

    @patch('agno.db.postgres.postgres.is_table_available')
    @patch('agno.db.postgres.postgres.is_valid_table')
    def test_get_or_create_table_existing_valid(self, mock_is_valid, mock_is_available, postgres_db, mock_session):
        """Test getting existing valid table"""
        mock_is_available.return_value = True
        mock_is_valid.return_value = True
        
        postgres_db.Session = Mock(return_value=mock_session)
        
        mock_table = Mock(spec=Table)
        with patch.object(Table, '__new__', return_value=mock_table):
            table = postgres_db._get_or_create_table("test_table", "sessions", "test_schema")
        
        assert table == mock_table
        mock_is_available.assert_called_once()
        mock_is_valid.assert_called_once()

    @patch('agno.db.postgres.postgres.is_table_available')
    def test_get_or_create_table_not_available(self, mock_is_available, postgres_db, mock_session):
        """Test creating table when not available"""
        mock_is_available.return_value = False
        
        postgres_db.Session = Mock(return_value=mock_session)
        
        mock_table = Mock(spec=Table)
        with patch.object(postgres_db, '_create_table', return_value=mock_table):
            table = postgres_db._get_or_create_table("test_table", "sessions", "test_schema")
        
        assert table == mock_table
        postgres_db._create_table.assert_called_once_with(
            table_name="test_table",
            table_type="sessions",
            db_schema="test_schema"
        )

    @patch('agno.db.postgres.postgres.is_table_available')
    @patch('agno.db.postgres.postgres.is_valid_table')
    def test_get_or_create_table_invalid_schema(self, mock_is_valid, mock_is_available, postgres_db, mock_session):
        """Test error when table exists but has invalid schema"""
        mock_is_available.return_value = True
        mock_is_valid.return_value = False
        
        postgres_db.Session = Mock(return_value=mock_session)
        
        with pytest.raises(ValueError, match="has an invalid schema"):
            postgres_db._get_or_create_table("test_table", "sessions", "test_schema")

    @patch('agno.db.postgres.postgres.is_table_available')
    @patch('agno.db.postgres.postgres.is_valid_table')
    def test_get_or_create_table_load_error(self, mock_is_valid, mock_is_available, postgres_db, mock_session):
        """Test error when loading existing table fails"""
        mock_is_available.return_value = True
        mock_is_valid.return_value = True
        
        postgres_db.Session = Mock(return_value=mock_session)
        
        with patch.object(Table, '__new__', side_effect=Exception("Load error")):
            with pytest.raises(Exception):
                postgres_db._get_or_create_table("test_table", "sessions", "test_schema")


class TestTableSchemaDefinitions:
    """Test the schema definitions themselves"""
    
    def test_get_table_schema_definition_sessions(self):
        """Test getting session table schema"""
        schema = get_table_schema_definition("sessions")
        assert schema == SESSION_TABLE_SCHEMA
        assert "session_id" in schema
        assert schema["session_id"]["nullable"] is False
        assert "_unique_constraints" in schema
        
    def test_get_table_schema_definition_memories(self):
        """Test getting memory table schema"""
        schema = get_table_schema_definition("memories")
        assert schema == MEMORY_TABLE_SCHEMA
        assert "memory_id" in schema
        assert schema["memory_id"]["primary_key"] is True
        
    def test_get_table_schema_definition_evals(self):
        """Test getting eval table schema"""
        schema = get_table_schema_definition("evals")
        assert schema == EVAL_TABLE_SCHEMA
        assert "run_id" in schema
        assert schema["eval_type"]["nullable"] is False
        
    def test_get_table_schema_definition_knowledge(self):
        """Test getting knowledge table schema"""
        schema = get_table_schema_definition("knowledge")
        assert schema == KNOWLEDGE_TABLE_SCHEMA
        assert "id" in schema
        assert schema["name"]["nullable"] is False
        
    def test_get_table_schema_definition_metrics(self):
        """Test getting metrics table schema"""
        schema = get_table_schema_definition("metrics")
        assert schema == METRICS_TABLE_SCHEMA
        assert "date" in schema
        assert schema["date"]["index"] is True
        assert "_unique_constraints" in schema
        
    def test_get_table_schema_definition_invalid(self):
        """Test getting schema for invalid table type"""
        with pytest.raises(ValueError, match="Unknown table type"):
            get_table_schema_definition("invalid_table")


class TestPostgresDbIntegration:
    """Integration tests using real PostgreSQL database"""

    @pytest.fixture
    def postgres_engine(self):
        """Create a PostgreSQL engine for testing using the actual database setup"""
        # Use the same connection string as the actual implementation
        db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai_test"  # Using ai_test database for tests
        
        try:
            engine = create_engine(db_url)
            # Test connection
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                conn.commit()
            
            yield engine
            
            # Cleanup: Drop all test tables after tests
            with engine.connect() as conn:
                # Drop test schema and all its tables
                conn.execute(text("DROP SCHEMA IF EXISTS test_schema CASCADE"))
                conn.commit()
                
        except Exception as e:
            pytest.skip(f"PostgreSQL not available for integration tests: {e}")

    @pytest.fixture
    def postgres_db_real(self, postgres_engine):
        """Create PostgresDb with real PostgreSQL engine"""
        return PostgresDb(
            db_engine=postgres_engine,
            db_schema="test_schema",  # Use test schema to avoid conflicts
            session_table="test_sessions",
            memory_table="test_memories",
            metrics_table="test_metrics",
            eval_table="test_evals",
            knowledge_table="test_knowledge"
        )

    def test_init_with_db_url(self):
        """Test initialization with actual database URL format"""
        db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai_test"
        
        try:
            db = PostgresDb(db_url=db_url, session_table="sessions")
            assert db.db_url == db_url
            assert db.session_table_name == "sessions"
            assert db.db_schema == "ai"  # Default schema
            
            # Test connection
            with db.Session() as sess:
                result = sess.execute(text("SELECT 1"))
                assert result.scalar() == 1
                
        except Exception as e:
            pytest.skip(f"Cannot connect to PostgreSQL: {e}")

    def test_create_session_table_integration(self, postgres_db_real):
        """Test actual session table creation with PostgreSQL"""
        # Create table
        table = postgres_db_real._create_table("test_sessions", "sessions", "test_schema")
        
        # Verify table exists in database with correct schema
        with postgres_db_real.Session() as sess:
            result = sess.execute(
                text("SELECT table_name FROM information_schema.tables "
                     "WHERE table_schema = :schema AND table_name = :table"),
                {"schema": "test_schema", "table": "test_sessions"}
            )
            assert result.fetchone() is not None
        
        # Verify columns exist and have correct types
        with postgres_db_real.Session() as sess:
            result = sess.execute(
                text("SELECT column_name, data_type, is_nullable "
                     "FROM information_schema.columns "
                     "WHERE table_schema = :schema AND table_name = :table "
                     "ORDER BY ordinal_position"),
                {"schema": "test_schema", "table": "test_sessions"}
            )
            columns = {row[0]: {"type": row[1], "nullable": row[2]} for row in result}
            
            # Verify key columns
            assert "session_id" in columns
            assert columns["session_id"]["nullable"] == "NO"
            assert "created_at" in columns
            assert columns["created_at"]["type"] == "bigint"
            assert "session_data" in columns
            assert columns["session_data"]["type"] in ["json", "jsonb"]

    def test_create_metrics_table_with_constraints(self, postgres_db_real):
        """Test creating metrics table with unique constraints"""
        table = postgres_db_real._create_table("test_metrics", "metrics", "test_schema")
        
        # Verify unique constraint exists
        with postgres_db_real.Session() as sess:
            result = sess.execute(
                text("SELECT constraint_name FROM information_schema.table_constraints "
                     "WHERE table_schema = :schema AND table_name = :table "
                     "AND constraint_type = 'UNIQUE'"),
                {"schema": "test_schema", "table": "test_metrics"}
            )
            constraints = [row[0] for row in result]
            assert any("uq_metrics_date_period" in c for c in constraints)

    def test_create_table_with_indexes(self, postgres_db_real):
        """Test that indexes are created correctly"""
        table = postgres_db_real._create_table("test_memories", "memories", "test_schema")
        
        # Verify indexes exist
        with postgres_db_real.Session() as sess:
            result = sess.execute(
                text("SELECT indexname FROM pg_indexes "
                     "WHERE schemaname = :schema AND tablename = :table"),
                {"schema": "test_schema", "table": "test_memories"}
            )
            indexes = [row[0] for row in result]
            
            # Should have indexes on user_id and last_updated
            assert any("user_id" in idx for idx in indexes)
            assert any("last_updated" in idx for idx in indexes)

    def test_schema_creation(self, postgres_db_real):
        """Test that schema is created if it doesn't exist"""
        # Use a unique schema name
        unique_schema = f"test_schema_{uuid4().hex[:8]}"
        
        with patch('agno.db.postgres.create_schema') as mock_create_schema:
            postgres_db_real._create_table("test_table", "sessions", unique_schema)
            
            # Verify create_schema was called
            mock_create_schema.assert_called_once()

    def test_get_or_create_existing_table(self, postgres_db_real):
        """Test getting an existing table"""
        # First create the table
        postgres_db_real._create_table("test_sessions", "sessions", "test_schema")
        
        # Clear the cached table attribute
        if hasattr(postgres_db_real, 'session_table'):
            delattr(postgres_db_real, 'session_table')
        
        # Now get it again - should not recreate
        with patch.object(postgres_db_real, '_create_table') as mock_create:
            table = postgres_db_real._get_or_create_table("test_sessions", "sessions", "test_schema")
            
            # Should not call create since table exists
            mock_create.assert_not_called()
            
        assert table.name == "test_sessions"

    def test_full_workflow(self, postgres_db_real):
        """Test a complete workflow of creating and using tables"""
        # Get tables (will create them)
        session_table = postgres_db_real._get_table("sessions")
        memory_table = postgres_db_real._get_table("memories")
        
        # Verify tables are cached
        assert hasattr(postgres_db_real, 'session_table')
        assert hasattr(postgres_db_real, 'memory_table')
        
        # Verify we can insert data (basic smoke test)
        with postgres_db_real.Session() as sess:
            # Insert a test session
            sess.execute(
                session_table.insert().values(
                    session_id="test-session-123",
                    session_type="agent",
                    created_at=int(datetime.now(timezone.utc).timestamp() * 1000),
                    session_data={"test": "data"}
                )
            )
            sess.commit()
            
            # Query it back
            result = sess.execute(
                session_table.select().where(
                    session_table.c.session_id == "test-session-123"
                )
            ).fetchone()
            
            assert result is not None
            assert result.session_type == "agent"


# Add a pytest configuration to run integration tests separately
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: mark test as integration test requiring PostgreSQL"
    )


# Mark all integration tests
pytestmark = pytest.mark.integration


if __name__ == "__main__":
    pytest.main([__file__, "-v"])