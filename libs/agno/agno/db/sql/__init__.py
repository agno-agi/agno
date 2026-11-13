"""Shared SQLAlchemy implementations behind the sync and async SQL backends (SqliteDb, PostgresDb).

Each module here is the table-level code for one feature; the backends delegate to it so the two
dialects and the sync/async pairs cannot drift.
"""
