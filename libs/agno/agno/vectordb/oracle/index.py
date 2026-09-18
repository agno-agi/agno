"""Vector index configuration for OracleVector's ``optimize()`` step.

Live code consumed by ``optimize()`` -- not a dead configuration surface the
SingleStore store carries. Oracle 23ai's native VECTOR type supports two
index organizations, both created via ``CREATE VECTOR INDEX``:

- ``NEIGHBOR PARTITIONS`` (:class:`IVF`): an inverted-file, cluster-based
  index. No special server configuration needed; this is the default.
- ``INMEMORY NEIGHBOR GRAPH`` (:class:`HNSW`): a graph-based index (Oracle's
  own docs describe it as HNSW-like). Requires the ``vector_memory_size``
  initialization parameter to be configured on the server -- confirmed
  live: creating one on a server with no vector memory pool configured
  raises ``ORA-51962`` ("vector memory area is out of space"), a server
  configuration issue, not a syntax error.
"""

from typing import Any, Dict, Optional

from pydantic import BaseModel


class IVF(BaseModel):
    """Partition-based ANN vector index (``ORGANIZATION NEIGHBOR PARTITIONS``).

    Args:
        name: Index name. Auto-generated from the table name if not given.
        target_accuracy: Target accuracy percentage (1-100) the index aims
            for; higher costs more build time and index size.
        parameters: Extra ``PARAMETERS`` clause tunables (e.g.
            ``{"NEIGHBOR PARTITIONS": 50}``), passed through verbatim.
    """

    name: Optional[str] = None
    target_accuracy: int = 95
    parameters: Dict[str, Any] = {}


class HNSW(BaseModel):
    """Graph-based ANN vector index (``ORGANIZATION INMEMORY NEIGHBOR GRAPH``).

    Requires ``vector_memory_size`` to be configured on the server (a static
    parameter needing an instance restart to change) -- see this module's
    own docstring.

    Args:
        name: Index name. Auto-generated from the table name if not given.
        target_accuracy: Target accuracy percentage (1-100) the index aims for.
        parameters: Extra ``PARAMETERS`` clause tunables (e.g.
            ``{"NEIGHBORS": 32, "EFCONSTRUCTION": 200}``), passed through verbatim.
    """

    name: Optional[str] = None
    target_accuracy: int = 95
    parameters: Dict[str, Any] = {}
