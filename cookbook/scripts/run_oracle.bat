docker run -d ^
  --name agno-oracle ^
  -e ORACLE_PASSWORD=ai ^
  -e APP_USER=ai ^
  -e APP_USER_PASSWORD=ai ^
  -p 1521:1521 ^
  gvenzl/oracle-free:latest

echo Waiting for Oracle to become available (this can take a couple of minutes on first start)...
timeout /t 90 /nobreak

echo Configuring vector_memory_size for HNSW...
docker exec agno-oracle sqlplus -s sys/ai@localhost:1521/FREEPDB1 as sysdba "ALTER SYSTEM SET vector_memory_size = 256M SCOPE = SPFILE;"
docker restart agno-oracle
timeout /t 60 /nobreak

set ORACLE_HOST=localhost
set ORACLE_PORT=1521
set ORACLE_SERVICE_NAME=FREEPDB1
set ORACLE_USER=ai
set ORACLE_PASSWORD=ai
set ORACLE_DB_URL=oracle+oracledb://ai:ai@localhost:1521/?service_name=FREEPDB1
