docker run -d \
 --rm --pull always \
 -p 8000:8000 \
 --name surrealdb \
 surrealdb/surrealdb:latest start --user root --pass root