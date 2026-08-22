docker run -d ^
  --name oracle ^
  -e ORACLE_PWD=ai ^
  -p 1521:1521 ^
  container-registry.oracle.com/database/free:latest

:wait
docker logs oracle 2>&1 | findstr /C:"DATABASE IS READY TO USE" >nul || (timeout /t 10 /nobreak >nul & goto wait)

docker exec oracle bash -c "printf 'ALTER SESSION SET CONTAINER = FREEPDB1;\nCREATE USER ai IDENTIFIED BY ai QUOTA UNLIMITED ON users;\nGRANT CONNECT, RESOURCE TO ai;\n' | sqlplus -s -L / as sysdba"
