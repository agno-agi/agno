# Agno Database Migrations

This directory contains the migrations for the Agno database.

Migrations are only required for databases that support schema migrations (PostgreSQL, MySQL, SQLite, SingleStore).

**Note:** If you have never used the migration manager, you are considered to be on `v2.0.0` of the schema and do not yet have a schema version stored in the database.  After running your first migration, the schema version will be stored in the database for tracking future migrations.


## How to use the migration manager

The migration manager is a class that can be used to manage the migrations for the Agno database.

To upgrade your database to the latest version, you can use the following code:
```python
from agno.db.migrations.manager import MigrationManager

MigrationManager(db).up()
```

To upgrade to a specific version, you can use the following code:
```python
from agno.db.migrations.manager import MigrationManager

MigrationManager(db).up("v2.3.0")
```

To downgrade your database to a specific version, you can use the following code:
```python
from agno.db.migrations.manager import MigrationManager

MigrationManager(db).down("v2.3.0")
```

To see which version your database is currently at, you can use the following code:
```python
from agno.db.migrations.manager import MigrationManager

print(MigrationManager(db).get_current_version())
```