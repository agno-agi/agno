"""Schemas for the pluggable authorization tier.

These six tables back the managed-roles product surface (``agno.os.authz``): the policy
and assignment tables the native policy engine decides from, the role metadata a
frontend renders, the credential-less user directory that carries the disabled-user
kill switch, and the two audit trails (who changed what, and every allow/deny).

They live here -- alongside every other agno table schema -- and are reached through the
``BaseDb`` contract (the ``*_authz_*`` methods, implemented by the sync SQLAlchemy
backends and inherited as ``NotImplementedError`` everywhere else) rather than being
declared inside the authz components. That means one place owns the schema, the tables
are created by the same schema-aware, migration-aware path as the rest of agno, they
honour a backend's configured schema and table-name overrides, and a database that
cannot support them says so plainly instead of being duck-typed for a SQLAlchemy engine
and failing later.

Column widths are deliberately unbounded (``String`` with no length): subjects are JWT
``sub`` claims and resources are scope strings, neither of which has a natural limit,
and the composite primary keys they take part in would otherwise collide with backend
index-length limits.
"""

try:
    from sqlalchemy.types import BigInteger, Boolean, String, Text
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")

# Table types (the keys passed to BaseDb._get_table / get_table_schema_definition). The
# default table names live on BaseDb (authz_*_table_name) so a deployment can rename them
# like any other agno table.
AUTHZ_POLICY = "authz_policy"
AUTHZ_GROUPING = "authz_grouping"
AUTHZ_ROLES = "authz_roles"
AUTHZ_USERS = "authz_users"
AUTHZ_AUDIT = "authz_audit"
AUTHZ_DECISIONS = "authz_decisions"

# What a role may do, as (resource, action, effect). Deny-overrides is evaluated over
# these rows, so ``effect`` is load-bearing and never nullable.
AUTHZ_POLICY_TABLE_SCHEMA = {
    "role": {"type": String, "primary_key": True, "nullable": False},
    "resource": {"type": String, "primary_key": True, "nullable": False},
    "action": {"type": String, "primary_key": True, "nullable": False},
    "effect": {"type": String, "nullable": False},
}

# Who holds which role. The same table expresses role inheritance (a role assigned to a
# role), which is why subjects and roles share one namespace.
AUTHZ_GROUPING_TABLE_SCHEMA = {
    "subject": {"type": String, "primary_key": True, "nullable": False},
    # The composite PK indexes (subject, role) and so covers "what roles does this
    # subject hold?", but NOT the reverse lookup by role alone. Every subject decision
    # does exactly that -- the role-name collision guard asks whether anything is
    # assigned to this name -- so without this index authorization is O(assignments):
    # measured at 3.65ms per decision on 50k subjects, versus 0.47ms with it.
    "role": {"type": String, "primary_key": True, "nullable": False, "index": True},
}

# Presentation metadata for a role. The policy above is the authority on what a role may
# do; this is what an admin UI renders.
AUTHZ_ROLES_TABLE_SCHEMA = {
    "slug": {"type": String, "primary_key": True, "nullable": False},
    "name": {"type": String, "nullable": True},
    "description": {"type": Text, "nullable": True},
    "is_default": {"type": Boolean, "nullable": False},
    "created_at": {"type": BigInteger, "nullable": False},
    "updated_at": {"type": BigInteger, "nullable": False},
}

# The credential-less user directory (the no-IdP tier). Identity is still asserted by the
# JWT; this stores no credentials. ``disabled`` is the kill switch -- a revocation that
# outlives a still-valid token -- which is why this table must be persisted and shared
# across replicas rather than living in a process-local dict.
AUTHZ_USERS_TABLE_SCHEMA = {
    "id": {"type": String, "primary_key": True, "nullable": False},  # the JWT sub
    "email": {"type": String, "nullable": True},
    "name": {"type": String, "nullable": True},
    "disabled": {"type": Boolean, "nullable": False},
    "created_at": {"type": BigInteger, "nullable": False},
    "updated_at": {"type": BigInteger, "nullable": False, "index": True},
    "user_metadata": {"type": Text, "nullable": True},
}

# The change trail: who changed what. Append-only.
AUTHZ_AUDIT_TABLE_SCHEMA = {
    "event_id": {"type": String, "primary_key": True, "nullable": False},
    "action": {"type": String, "nullable": False},
    "actor": {"type": String, "nullable": True},
    "target": {"type": String, "nullable": True},
    "before": {"type": Text, "nullable": True},
    "after": {"type": Text, "nullable": True},
    "timestamp": {"type": BigInteger, "nullable": False, "index": True},
}

# The access trail: every allow/deny decision, so an audit covers who was let in as well
# as who changed the rules.
AUTHZ_DECISIONS_TABLE_SCHEMA = {
    "event_id": {"type": String, "primary_key": True, "nullable": False},
    "allowed": {"type": Boolean, "nullable": False},
    "actor": {"type": String, "nullable": True},
    "target": {"type": String, "nullable": True},
    "reason": {"type": String, "nullable": True},
    "required_scopes": {"type": Text, "nullable": True},
    "scopes": {"type": Text, "nullable": True},
    "token_ref": {"type": String, "nullable": True},
    "timestamp": {"type": BigInteger, "nullable": False, "index": True},
}

# Registered in each SQLAlchemy backend's get_table_schema_definition so the authz tables
# are created by the normal schema-aware path.
AUTHZ_TABLE_SCHEMAS = {
    AUTHZ_POLICY: AUTHZ_POLICY_TABLE_SCHEMA,
    AUTHZ_GROUPING: AUTHZ_GROUPING_TABLE_SCHEMA,
    AUTHZ_ROLES: AUTHZ_ROLES_TABLE_SCHEMA,
    AUTHZ_USERS: AUTHZ_USERS_TABLE_SCHEMA,
    AUTHZ_AUDIT: AUTHZ_AUDIT_TABLE_SCHEMA,
    AUTHZ_DECISIONS: AUTHZ_DECISIONS_TABLE_SCHEMA,
}

# Maps each table type to the BaseDb attribute holding its (renameable) table name, so a
# backend's _get_table dispatch can resolve all six in one branch.
AUTHZ_TABLE_NAME_ATTRS = {
    AUTHZ_POLICY: "authz_policy_table_name",
    AUTHZ_GROUPING: "authz_grouping_table_name",
    AUTHZ_ROLES: "authz_roles_table_name",
    AUTHZ_USERS: "authz_users_table_name",
    AUTHZ_AUDIT: "authz_audit_table_name",
    AUTHZ_DECISIONS: "authz_decisions_table_name",
}
