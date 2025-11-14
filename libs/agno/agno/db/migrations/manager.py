from agno.db.base import BaseDb
import os
import importlib
from typing import Optional

from agno.utils.log import log_info

class MigrationManager:
    def __init__(self, db: BaseDb):
        self.db = db
        if db.__class__.__name__ not in ["PostgresDb", "AsyncPostgresDb", "MySQLDb", "SQLiteDb", "AsyncSQLiteDb", "SingleStoreDb"]:
            raise ValueError(f"Database {db.__class__.__name__} does not require migrations")
        
        # Get all migration versions and normalise them (filename, version string e.g. "v2.3.0")
        self.normalised_migration_versions = [(f, f.split(".")[0].replace("_", ".")) for f in os.listdir("agno/db/migrations/versions")]

    def get_current_version(self) -> str:
        return self.db.get_latest_schema_version()
    
    def up(self, target_version: Optional[str] = None):
        current_version = self.db.get_latest_schema_version()
        log_info(f"Current schema version: {current_version}")
        
        # Find files after the current version
        latest_version = None
        for version_filename, normalised_version in self.normalised_migration_versions:
            if normalised_version > current_version:
                if target_version and normalised_version > target_version:
                    break
                log_info(f"Applying migration: {normalised_version}")
                self._up_migration(version_filename)
                log_info(f"Successfully applied migration: {normalised_version}")
                latest_version = normalised_version
        
        if latest_version:
            log_info(f"Storing version {latest_version} in database")
            self.db.upsert_schema_version(latest_version)
            log_info(f"Successfully stored version {latest_version} in database")

    def _up_migration(self, version_filename: str):
        migration_module = importlib.import_module(f"agno.db.migrations.versions.{version_filename}")
        migration_module.up(self.db)
        
    def down(self, target_version: str):
        current_version = self.db.get_latest_schema_version()
        log_info(f"Current schema version: {current_version}")
        
        if target_version > current_version:
            raise ValueError(f"Target version {target_version} is greater than current version {current_version}")
        
        latest_version = None
        # Run down migration for all versions between target and current (include down of current version)
        # Apply down migrations in reverse order to ensure dependencies are met
        for version_filename, normalised_version in reversed(self.normalised_migration_versions):
            if normalised_version > target_version and normalised_version <= current_version:
                log_info(f"Reverting migration: {normalised_version}")
                self._down_migration(version_filename)
                log_info(f"Successfully reverted migration: {normalised_version}")
                latest_version = normalised_version
        
        if latest_version:
            log_info(f"Storing version {latest_version} in database")
            self.db.upsert_schema_version(latest_version)
            log_info(f"Successfully stored version {latest_version} in database")
                
        
    def _down_migration(self, version_filename: str):
        migration_module = importlib.import_module(f"agno.db.migrations.versions.{version_filename}")
        migration_module.down(self.db)