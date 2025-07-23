docker run -d ^
  --name mysql ^
  -e MYSQL_ROOT_PASSWORD=ai ^
  -e MYSQL_DATABASE=ai ^
  -e MYSQL_USER=ai ^
  -e MYSQL_PASSWORD=ai ^
  -p 3306:3306 ^
  -d mysql:8 