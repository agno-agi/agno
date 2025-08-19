docker run -d --name singlestoredb ^
  -p 3306:3306 ^
  -p 8080:8080 ^
  -v /tmp:/var/lib/memsql ^
  -e ROOT_PASSWORD=admin ^
  -e SINGLESTORE_DB=AGNO ^
  -e SINGLESTORE_USER=root ^
  -e SINGLESTORE_PASSWORD=password ^
  memsql/cluster-in-a-box

docker start singlestoredb

set SINGLESTORE_HOST=localhost
set SINGLESTORE_PORT=3306
set SINGLESTORE_USERNAME=root
set SINGLESTORE_PASSWORD=admin
set SINGLESTORE_DATABASE=AGNO 