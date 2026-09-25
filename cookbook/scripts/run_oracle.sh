#!/bin/bash

# One-command local Oracle Database for developing against agno's Oracle
# storage and vector database adapters. Uses gvenzl/oracle-free (community,
# no registry login or license click needed) rather than Oracle's own
# container-registry.oracle.com image, so a fresh clone works without any
# account setup. Both wrap the same Oracle Database Free (23ai) edition.
#
# Storage supports Oracle 19c and later; the vector database requires 23ai
# and later, which is what this script provides. See
# cookbook/06_storage/oracle/README.md for the version matrix and how
# db_schema and create_schema behave differently from Postgres on Oracle.

if [ "$(docker ps -aq -f name=agno-oracle)" ]; then
    echo "Removing existing agno-oracle container..."
    docker rm -f agno-oracle
fi

echo "Starting Oracle Database Free container..."
docker run -d --name agno-oracle \
  -p 1521:1521 \
  -e ORACLE_PASSWORD=ai \
  -e APP_USER=ai \
  -e APP_USER_PASSWORD=ai \
  gvenzl/oracle-free:latest

echo "Waiting for Oracle to become available (this can take a couple of minutes on first start)..."
until docker logs agno-oracle 2>&1 | grep -q "DATABASE IS READY TO USE"; do
  sleep 5
  echo "  ...still starting"
done
echo "Oracle is ready."

# Vector search needs an in-memory area sized for the HNSW graph. 256M is
# enough for the cookbook examples; raise it for a larger corpus.
echo "Configuring vector_memory_size for HNSW..."
docker exec agno-oracle sqlplus -s sys/ai@localhost:1521/FREEPDB1 as sysdba <<'SQL'
ALTER SYSTEM SET vector_memory_size = 256M SCOPE = SPFILE;
SQL
RESTART_AT=$(date +%s)
docker restart agno-oracle >/dev/null
echo "Waiting for Oracle to come back up after the restart..."
# The pre-restart "ready" message is still in the accumulated log, so wait for
# one stamped after the restart rather than merely for the phrase to appear.
until docker logs --since "@${RESTART_AT}" agno-oracle 2>&1 | grep -q "DATABASE IS READY TO USE"; do
  sleep 5
  echo "  ...still restarting"
done

echo "Database setup complete!"

export ORACLE_HOST="localhost"
export ORACLE_PORT="1521"
export ORACLE_SERVICE_NAME="FREEPDB1"
export ORACLE_USER="ai"
export ORACLE_PASSWORD="ai"
export ORACLE_DB_URL="oracle+oracledb://ai:ai@localhost:1521/?service_name=FREEPDB1"
