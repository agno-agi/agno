"""Schemas for the built-in MCP OAuth authorization server's token store.

These five tables back ``AgentOSBuiltinAuth`` (``agno.os.mcp_auth_builtin``): the
OAuth authorization server the AgentOS MCP endpoint runs when a deployer opts in via
``AgentOS(mcp_auth=AgentOSBuiltinAuth(...))``. They live here -- alongside every other
agno table schema -- and are reached through the ``BaseDb`` contract (the
``*_mcp_oauth_*`` methods, implemented by the sync SQLAlchemy backends and inherited as
``NotImplementedError`` everywhere else) rather than defined inside the provider, so a
single place owns the schema and the store is created by the same schema-aware,
migration-aware path as the rest of agno.

The columns hold no replayable secrets: authorization codes and refresh tokens are
stored SHA-256-hashed (the ``*_hash`` primary keys), matching the service-account PAT
model, so a database read yields nothing that can be presented as a bearer.
"""

try:
    from sqlalchemy.types import BigInteger, String, Text
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")

# Table types (the keys passed to BaseDb._get_table / get_table_schema_definition). The
# default table names live on BaseDb (mcp_oauth_*_table_name) so a deployment can rename
# them like any other agno table.
MCP_OAUTH_CLIENTS = "mcp_oauth_clients"
MCP_OAUTH_TRANSACTIONS = "mcp_oauth_transactions"
MCP_OAUTH_CODES = "mcp_oauth_codes"
MCP_OAUTH_REFRESH_TOKENS = "mcp_oauth_refresh_tokens"
MCP_OAUTH_KEYS = "mcp_oauth_keys"

# Dynamic Client Registration records. Public clients only (no client secret is ever
# stored); ``consumed_at`` marks a client that completed the deployer-approved consent
# flow, so unconsumed rows can be flood-pruned while consumed ones are kept.
MCP_OAUTH_CLIENTS_TABLE_SCHEMA = {
    "client_id": {"type": String, "primary_key": True, "nullable": False},
    "client_metadata": {"type": Text, "nullable": False},
    "created_at": {"type": BigInteger, "nullable": False, "index": True},
    "consumed_at": {"type": BigInteger, "nullable": True},
}

# Pending authorizations awaiting the consent POST. Short-lived; ``expires_at`` is
# indexed for the expiry sweep and the oldest-first eviction cap.
MCP_OAUTH_TRANSACTIONS_TABLE_SCHEMA = {
    "txn_id": {"type": String, "primary_key": True, "nullable": False},
    "client_id": {"type": String, "nullable": False},
    "params": {"type": Text, "nullable": False},
    "expires_at": {"type": BigInteger, "nullable": False, "index": True},
}

# Authorization codes, SHA-256-hashed at rest. Single-use (deleted on exchange).
MCP_OAUTH_CODES_TABLE_SCHEMA = {
    "code_hash": {"type": String, "primary_key": True, "nullable": False},
    "payload": {"type": Text, "nullable": False},
    "expires_at": {"type": BigInteger, "nullable": False, "index": True},
}

# Refresh tokens, SHA-256-hashed at rest. Rotated (deleted) on every use. ``family_id``
# ties every token in a rotation chain together so reuse of a rotated token can revoke the
# whole family (OAuth 2.1 / RFC 9700 reuse detection); it is indexed for that delete.
MCP_OAUTH_REFRESH_TOKENS_TABLE_SCHEMA = {
    "token_hash": {"type": String, "primary_key": True, "nullable": False},
    "client_id": {"type": String, "nullable": False},
    "scopes": {"type": Text, "nullable": False},
    "expires_at": {"type": BigInteger, "nullable": False, "index": True},
    "family_id": {"type": String, "nullable": False, "index": True},
}

# HS256 signing keys, newest-first by ``created_at``. The newest signs; any verifies (the
# rotation overlap). ``secret`` is the key material persisted only when no env-primary
# key (``AGENTOS_MCP_SIGNING_KEY``) is set.
MCP_OAUTH_KEYS_TABLE_SCHEMA = {
    "kid": {"type": String, "primary_key": True, "nullable": False},
    "secret": {"type": Text, "nullable": False},
    "created_at": {"type": BigInteger, "nullable": False, "index": True},
}

# Registered in each SQLAlchemy backend's get_table_schema_definition so the built-in AS
# store is created by the normal schema-aware path.
MCP_OAUTH_TABLE_SCHEMAS = {
    MCP_OAUTH_CLIENTS: MCP_OAUTH_CLIENTS_TABLE_SCHEMA,
    MCP_OAUTH_TRANSACTIONS: MCP_OAUTH_TRANSACTIONS_TABLE_SCHEMA,
    MCP_OAUTH_CODES: MCP_OAUTH_CODES_TABLE_SCHEMA,
    MCP_OAUTH_REFRESH_TOKENS: MCP_OAUTH_REFRESH_TOKENS_TABLE_SCHEMA,
    MCP_OAUTH_KEYS: MCP_OAUTH_KEYS_TABLE_SCHEMA,
}

# Maps each table type to the BaseDb attribute holding its (renameable) table name, so a
# backend's _get_table dispatch can resolve all five in one branch.
MCP_OAUTH_TABLE_NAME_ATTRS = {
    MCP_OAUTH_CLIENTS: "mcp_oauth_clients_table_name",
    MCP_OAUTH_TRANSACTIONS: "mcp_oauth_transactions_table_name",
    MCP_OAUTH_CODES: "mcp_oauth_codes_table_name",
    MCP_OAUTH_REFRESH_TOKENS: "mcp_oauth_refresh_tokens_table_name",
    MCP_OAUTH_KEYS: "mcp_oauth_keys_table_name",
}
