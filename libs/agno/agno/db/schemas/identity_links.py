"""Schemas for identity links: an account on another service linked to an AgentOS principal.

A Slack member links their account to the principal they sign in to AgentOS as, so a Slack
message runs with that principal's roles. The person proves both sides: the principal with
their AgentOS token when they ask for a link code, the outside account by redeeming the code
through the service's signed request.

Only the SQLAlchemy backends (``PostgresDb``, ``SqliteDb`` and their async twins) implement
the ``*_identity_link*`` methods that use these tables.
"""

try:
    from sqlalchemy.types import BigInteger, String
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")

IDENTITY_LINKS = "identity_links"
IDENTITY_LINK_CODES = "identity_link_codes"

# ``tenant`` scopes the outside id (a Slack workspace); it is "" when the service has none.
IDENTITY_LINKS_TABLE_SCHEMA = {
    "provider": {"type": String, "primary_key": True, "nullable": False},
    "tenant": {"type": String, "primary_key": True, "nullable": False},
    "external_id": {"type": String, "primary_key": True, "nullable": False},
    # Indexed: unlinking and listing go by principal
    "principal_id": {"type": String, "nullable": False, "index": True},
    "created_at": {"type": BigInteger, "nullable": False},
}

# One-time link codes, stored as their SHA-256 so a database read never yields a usable code.
# A code is deleted when redeemed, and an expired one can no longer be redeemed.
IDENTITY_LINK_CODES_TABLE_SCHEMA = {
    "code_hash": {"type": String, "primary_key": True, "nullable": False},
    "provider": {"type": String, "nullable": False},
    "principal_id": {"type": String, "nullable": False, "index": True},
    "expires_at": {"type": BigInteger, "nullable": False, "index": True},
    "created_at": {"type": BigInteger, "nullable": False},
}

# Registered in each SQLAlchemy backend's get_table_schema_definition
IDENTITY_LINK_TABLE_SCHEMAS = {
    IDENTITY_LINKS: IDENTITY_LINKS_TABLE_SCHEMA,
    IDENTITY_LINK_CODES: IDENTITY_LINK_CODES_TABLE_SCHEMA,
}

# Maps each table type to the BaseDb attribute holding its (renameable) table name
IDENTITY_LINK_TABLE_NAME_ATTRS = {
    IDENTITY_LINKS: "identity_links_table_name",
    IDENTITY_LINK_CODES: "identity_link_codes_table_name",
}
