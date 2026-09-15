"""Oracle server version detection and the schema capabilities it implies.

Storage supports Oracle 19c and later; the vector database requires 23ai and
later, where the native VECTOR type exists. Detection reads
PRODUCT_COMPONENT_VERSION rather than V$INSTANCE: the latter is a dynamic
performance view that requires a privilege (SELECT ANY DICTIONARY, or a grant
on V_$INSTANCE) application users frequently do not hold, while
PRODUCT_COMPONENT_VERSION is a public view any connected user can read.

For a table that already exists, the schema variant must come from reflecting
the actual column type, never from the server version: a table created on 19c
and later reached from a 21c+ server must continue to be read as it was
written. This module only detects server capabilities; the reflection-wins
rule is implemented by the adapter's table resolution, not here.
"""

import weakref
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine

# PRODUCT_COMPONENT_VERSION, not V$INSTANCE: the latter requires a privilege
# application users frequently do not have. See module docstring.
_VERSION_QUERY = text(
    "SELECT version, version_full FROM product_component_version WHERE product LIKE 'Oracle%' FETCH FIRST 1 ROWS ONLY"
)


@dataclass(frozen=True)
class OracleCapabilities:
    """Capabilities of a connected Oracle server, derived from its version.

    ``major`` is the leading version component (e.g. 19, 21, 23). Oracle's
    23ai and 26ai releases both report major version 23 (26ai is a quarterly
    update to the 23ai codebase, not a new major version), so both correctly
    resolve to the same capability set here.
    """

    major: int
    full_version: str
    native_json: bool  # JSON datatype: 21c and later. Below that: CLOB CHECK (IS JSON).
    native_boolean: bool  # BOOLEAN datatype: 23ai and later. Below that: NUMBER(1).
    vector: bool  # VECTOR datatype and AI Vector Search: 23ai and later.

    @classmethod
    def from_version(cls, major: int, full_version: str) -> "OracleCapabilities":
        return cls(
            major=major,
            full_version=full_version,
            native_json=major >= 21,
            native_boolean=major >= 23,
            vector=major >= 23,
        )

    @classmethod
    def override(cls, *, json_storage: Optional[str] = None) -> "OracleCapabilities":
        """Build capabilities from an explicit override rather than detection.

        For locked-down environments where the application user cannot read
        PRODUCT_COMPONENT_VERSION. ``json_storage`` is either "native" (21c+
        behaviour) or "clob" (pre-21c behaviour); boolean and vector support
        are conservatively assumed absent, since an override caller is
        explicitly opting out of version-based inference and no other signal
        is available. Pass the concrete capability dataclass directly if more
        control is needed.
        """
        native_json = json_storage == "native"
        return cls(
            major=0, full_version="unknown (override)", native_json=native_json, native_boolean=False, vector=False
        )


# One cache entry per engine, so repeated adapter construction against the
# same engine (or the same URL through separate engines under test) does not
# repeat a version round trip. A WeakKeyDictionary rather than a plain dict
# keyed by id(engine): engines are routinely short-lived in tests, and a
# plain id() key can be silently reused by an unrelated, later-constructed
# engine once the original is garbage collected, serving it a stale entry.
_capabilities_cache: "weakref.WeakKeyDictionary[Engine, OracleCapabilities]" = weakref.WeakKeyDictionary()


def detect_capabilities(engine: Engine) -> OracleCapabilities:
    """Detect the connected Oracle server's version and derived capabilities.

    Raises RuntimeError if the version cannot be determined (for example, the
    connecting user cannot read PRODUCT_COMPONENT_VERSION) — pass
    ``json_storage`` explicitly to OracleDb/OracleVector to skip detection in
    that case rather than guessing at a variant.
    """
    cached = _capabilities_cache.get(engine)
    if cached is not None:
        return cached

    with engine.connect() as conn:
        row = conn.execute(_VERSION_QUERY).first()

    if row is None:
        raise RuntimeError(
            "Could not determine the Oracle Database version from PRODUCT_COMPONENT_VERSION. "
            "This can happen if the connecting user lacks SELECT on that view, or if it is "
            "empty on this installation. Pass json_storage explicitly to OracleDb/OracleVector "
            "to skip detection."
        )

    version_value, version_full = row[0], row[1] or row[0]
    major = int(str(version_value).split(".")[0])
    capabilities = OracleCapabilities.from_version(major, str(version_full))
    _capabilities_cache[engine] = capabilities
    return capabilities


# Separate cache keyed by AsyncEngine: a sync Engine and an AsyncEngine are
# different objects even when they wrap the same connection pool, so the two
# caches never collide and never need to agree on a key type.
_async_capabilities_cache: "weakref.WeakKeyDictionary[AsyncEngine, OracleCapabilities]" = weakref.WeakKeyDictionary()


async def adetect_capabilities(engine: AsyncEngine) -> OracleCapabilities:
    """Async twin of ``detect_capabilities``. Never opens a sync engine or
    connection -- the async adapter's whole reason to resolve capabilities
    this way rather than reusing the sync detector directly.
    """
    cached = _async_capabilities_cache.get(engine)
    if cached is not None:
        return cached

    async with engine.connect() as conn:
        result = await conn.execute(_VERSION_QUERY)
        row = result.first()

    if row is None:
        raise RuntimeError(
            "Could not determine the Oracle Database version from PRODUCT_COMPONENT_VERSION. "
            "This can happen if the connecting user lacks SELECT on that view, or if it is "
            "empty on this installation. Pass json_storage explicitly to AsyncOracleDb "
            "to skip detection."
        )

    version_value, version_full = row[0], row[1] or row[0]
    major = int(str(version_value).split(".")[0])
    capabilities = OracleCapabilities.from_version(major, str(version_full))
    _async_capabilities_cache[engine] = capabilities
    return capabilities
