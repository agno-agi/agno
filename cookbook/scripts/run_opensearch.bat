@echo off
REM Start OpenSearch in Docker
REM OpenSearch is an open-source search and analytics suite derived from Elasticsearch
REM This script runs OpenSearch with security disabled for local development

docker run -d ^
  --name opensearch ^
  -p 9200:9200 ^
  -p 9600:9600 ^
  -e "discovery.type=single-node" ^
  -e "DISABLE_SECURITY_PLUGIN=true" ^
  -e "OPENSEARCH_INITIAL_ADMIN_PASSWORD=Admin@123" ^
  opensearchproject/opensearch:latest

echo OpenSearch is starting...
echo API endpoint: http://localhost:9200
echo Wait a few seconds for OpenSearch to be ready
echo.
echo Test connection with: curl http://localhost:9200
