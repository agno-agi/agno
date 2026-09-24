# Agno Database Migrations

This is a guide on how to handle migrations for your Agno database.

- If you are coming from Agno v1, there are migration scripts that you should run.
- If you are already on Agno v2 and need to migrate your database to the latest version, you can use the migration manager.

## How to migrate from Agno v1 to v2

Before attempting this, make sure you have read the [Agno v2 Migration Guide](https://docs.agno.com/how-to/v2-migration) and are familiar with the changes in the new version.

- For migrating your "Storage" and "Memory" databases, use our migration script: `libs/agno/scripts/v1_to_v2/migrate_to_v2.py`
- For migrating your Vector Database, use our migration script: `libs/agno/scripts/v1_to_v2/migrate_to_v2_vector_db.py`
  
Notice:
- The script won’t cleanup the old tables, in case you still need them.
- The script is idempotent. If something goes wrong or if you stop it mid-run, you can run it again.
- Metrics are automatically converted from v1 to v2 format.

## Filesystem table (`agno_fs`) in v3.1

v3.1 keys the filesystem table by `(namespace, user_id, path)`. `user_id` is the user
partition: `""` for the shared partition (runs with no user), a user's id for their own.

The table is not part of the migration manager, because it belongs to `DbFileSystem`
(its own schema, and it can be built from a bare `db_url`). A table created by an
earlier release is refused with `SchemaOutdatedError` until it is upgraded, so the
key change is a deliberate step and never runs on its own. Upgrade it once, with the
application stopped, using the script:

```bash
python libs/agno/migrations/migrate_filesystem.py
```

Edit the connection in the script to match the application's, or call it from code:

```python
from agno.fs.db import DbFileSystem

DbFileSystem(db=my_postgres_db).upgrade_schema()
```

On PostgreSQL the upgrade is an `ALTER TABLE` (column plus key). SQLite cannot change
a key in place, so the table is rebuilt and swapped in one transaction. Existing rows
keep their namespace and land in the shared partition, so a custom
`users/{user_id}/...` template still finds its files. The upgrade is idempotent.

## How to use the migration manager

The migration manager is a class that can be used to manage the migrations for the Agno database.

**Note:** If you have never used the migration manager, you are considered to be on `v2.0.0` of the schema and do not yet have a schema version stored in the database.  After running your first migration, the schema version will be stored in the database for tracking future migrations.

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

To force the migration if necessary (perhaps there is a version mismatch in your `agno_schema_versions` table), you can use the following code:
```python
from agno.db.migrations.manager import MigrationManager

MigrationManager(db).up(force=True)
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