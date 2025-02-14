docker run -d --name singlestoredb \
  -p 3306:3306 \
  -p 8080:8080 \
  -v /tmp:/var/lib/memsql \
  -e ROOT_PASSWORD=admin \
  -e SINGLESTORE_DB=AGNO \
  -e SINGLESTORE_USER=root \
  -e SINGLESTORE_PASSWORD=password \
  memsql/cluster-in-a-box

docker start singlestoredb

export SINGLESTORE_HOST="localhost"
export SINGLESTORE_PORT="3306"
export SINGLESTORE_USERNAME="root"
export SINGLESTORE_PASSWORD="admin"
export SINGLESTORE_DATABASE="AGNO"
