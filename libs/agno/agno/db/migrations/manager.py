import importlib
from typing import Optional

from packaging import version as packaging_version
from packaging.version import Version

from agno.db.base import BaseDb
from agno.utils.log import log_error, log_info


class MigrationManager:
    """Manager class to handle database migrations"""

    available_versions: list[tuple[str, Version]] = [
        ("v2_0_0", packaging_version.parse("2.0.0")),
        ("v2_3_0", packaging_version.parse("2.3.0")),
    ]

    def __init__(self, db: BaseDb):
        self.db = db

    def up(self, target_version: Optional[str] = None):
        """Handle executing an up migration.

        Args:
            target_version: The version to migrate to, e.g. "v3.0.0". If not provided, the latest available version will be used.
        """

        # If not target version is provided, use the latest available version
        if not target_version:
            _target_version = self.available_versions[-1][1]
        else:
            _target_version = packaging_version.parse(target_version)

        current_version = packaging_version.parse(self.db.get_latest_schema_version())

        # If the target version is less or equal to the current version, no migrations needed
        if _target_version <= current_version:
            log_info(
                f"Target version {_target_version} is less or equal to current version: {current_version}. Skipping migration."
            )
            return

        log_info(f"Starting database migration. Current version: {current_version}. Target version: {_target_version}.")

        # Find files after the current version
        latest_version = None
        for version, normalised_version in self.available_versions:
            if normalised_version > current_version:
                if target_version and normalised_version > _target_version:
                    break

                log_info(f"Applying migration: {normalised_version}")
                self._up_migration(version)
                log_info(f"Successfully applied migration: {normalised_version}")

                latest_version = version

        if latest_version:
            log_info(f"Storing version {latest_version} in database")
            self.db.upsert_schema_version(latest_version)
            log_info(f"Successfully stored version {latest_version} in database")

    def _up_migration(self, version: str):
        """Run the database-specific logic to handle an up migration.

        Args:
            version: The version to migrate to, e.g. "v3.0.0"
        """
        migration_module = importlib.import_module(f"agno.db.migrations.versions.{version}")

        try:
            migration_module.up(self.db)
        except Exception as e:
            log_error(f"Error running migration to version {version}: {e}")
            raise

    def down(self, target_version: str):
        """Handle executing a down migration.

        Args:
            target_version: The version to migrate to. e.g. "v2.3.0"
        """
        _target_version = packaging_version.parse(target_version)
        current_version = packaging_version.parse(self.db.get_latest_schema_version())

        if _target_version >= current_version:
            raise ValueError(
                f"Target version {_target_version} is greater or equal to current version: {current_version}. Skipping migration."
            )

        latest_version = None
        # Run down migration for all versions between target and current (include down of current version)
        # Apply down migrations in reverse order to ensure dependencies are met
        for version, normalised_version in reversed(self.available_versions):
            if normalised_version > _target_version:
                log_info(f"Reverting migration: {version}")
                self._down_migration(version)
                log_info(f"Successfully reverted migration: {version}")
                latest_version = version

        if latest_version:
            log_info(f"Storing version {latest_version} in database")
            self.db.upsert_schema_version(latest_version)
            log_info(f"Successfully stored version {latest_version} in database")

    def _down_migration(self, version: str):
        """Run the database-specific logic to handle a down migration.

        Args:
            version: The version to migrate to, e.g. "v3.0.0"
        """
        migration_module = importlib.import_module(f"agno.db.migrations.versions.{version}.py")
        try:
            migration_module.down(self.db)
        except Exception as e:
            log_error(f"Error running migration to version {version}: {e}")
            raise
