from agno.vectordb.valkey.valkeydb import SearchType, ValkeyDb

# Alias to disambiguate from the ValkeyDb storage adapter in agno.db.valkey
ValkeyVectorDb = ValkeyDb

# Backwards-compat alias (deprecated, use ValkeyDb)
ValkeyDB = ValkeyDb

__all__ = [
    "ValkeyVectorDb",
    "ValkeyDb",
    "ValkeyDB",
    "SearchType",
]
