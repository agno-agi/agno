docker run -d \
  -e MYSQL_ROOT_PASSWORD=agno \
  -e MYSQL_DATABASE=agno \
  -e MYSQL_USER=agno \
  -e MYSQL_PASSWORD=agno \
  -p 3306:3306 \
  -v mysql_data:/var/lib/mysql \
  -v $(pwd)/cookbook/mysql-init:/docker-entrypoint-initdb.d \
  --name mysql \
  mysql:8.0
