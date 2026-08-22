docker run -d \
  --name oracle \
  -e ORACLE_PWD=ai \
  -p 1521:1521 \
  container-registry.oracle.com/database/free:latest

# The official image has no app-user bootstrap: wait for the database to finish
# initializing (first start takes a few minutes), then create the ai user in FREEPDB1.
until docker logs oracle 2>&1 | grep -q "DATABASE IS READY TO USE"; do
  sleep 10
done
docker exec oracle bash -c 'sqlplus -s -L / as sysdba <<SQL
ALTER SESSION SET CONTAINER = FREEPDB1;
CREATE USER ai IDENTIFIED BY ai QUOTA UNLIMITED ON users;
GRANT CONNECT, RESOURCE TO ai;
SQL'
