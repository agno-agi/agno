docker run -d ^
  -e CLICKHOUSE_DB=ai ^
  -e CLICKHOUSE_USER=ai ^
  -e CLICKHOUSE_PASSWORD=ai ^
  -e CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT=1 ^
  -v clickhouse_data:/var/lib/clickhouse/ ^
  -v clickhouse_log:/var/log/clickhouse-server/ ^
  -p 8123:8123 ^
  -p 9000:9000 ^
  --ulimit nofile=262144:262144 ^
  --name clickhouse-server ^
  clickhouse/clickhouse-server 