"""Schemas for identity links: an account on another service linked to an AgentOS principal.

A Slack member is linked to the AgentOS user they act as, so a Slack message runs with that
user's roles: the user whose ID is the member's confirmed Slack email, stored once found.

Only the SQLAlchemy backends (``PostgresDb``, ``SqliteDb`` and their async twins) implement
the ``*_identity_link*`` methods that use these tables.
"""

try:
    from sqlalchemy.types import BigInteger, String
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")

IDENTITY_LINKS = "identity_links"

# ``tenant`` scopes the outside id (a Slack workspace); it is "" when the service has none.
IDENTITY_LINKS_TABLE_SCHEMA = {
    "provider": {"type": String, "primary_key": True, "nullable": False},
    "tenant": {"type": String, "primary_key": True, "nullable": False},
    "external_id": {"type": String, "primary_key": True, "nullable": False},
    # Indexed: unlinking and listing go by principal
    "principal_id": {"type": String, "nullable": False, "index": True},
    "created_at": {"type": BigInteger, "nullable": False},
}

# Registered in each SQLAlchemy backend's get_table_schema_definition
IDENTITY_LINK_TABLE_SCHEMAS = {
    IDENTITY_LINKS: IDENTITY_LINKS_TABLE_SCHEMA,
}

# Maps each table type to the BaseDb attribute holding its (renameable) table name
IDENTITY_LINK_TABLE_NAME_ATTRS = {
    IDENTITY_LINKS: "identity_links_table_name",
}
