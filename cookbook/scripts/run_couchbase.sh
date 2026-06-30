docker run -d --name couchbase-server \
   -p 8091-8096:8091-8096 \
   -p 11210:11210 \
   -e COUCHBASE_ADMINISTRATOR_USERNAME=Administrator \
   -e COUCHBASE_ADMINISTRATOR_PASSWORD=password \
   couchbase:latest
