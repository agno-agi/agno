"""Session sandbox registry, shared by the SQL adapters."""

from typing import Any, Dict


def sandbox_table_schema(json_type: Any) -> Dict[str, Any]:
    from sqlalchemy import BigInteger, String

    return {
        "sandbox_id": {"type": String, "primary_key": True, "nullable": False},
        "session_id": {"type": String, "unique": True, "nullable": False},
        "agent_id": {"type": String, "nullable": False, "index": True},
        "user_id": {"type": String, "nullable": True, "index": True},
        "provider": {"type": String, "nullable": False},
        "provider_ref": {"type": String, "nullable": True},
        "status": {"type": String, "nullable": False, "index": True},
        "url": {"type": String, "nullable": True},
        "generation": {"type": BigInteger, "nullable": False},
        "revision": {"type": BigInteger, "nullable": False},
        "active_run_id": {"type": String, "nullable": True},
        "active_attempt": {"type": BigInteger, "nullable": True},
        "created_at": {"type": BigInteger, "nullable": False},
        "updated_at": {"type": BigInteger, "nullable": False},
        "last_active_at": {"type": BigInteger, "nullable": False},
        "metadata": {"type": json_type, "nullable": False},
    }
