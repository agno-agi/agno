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