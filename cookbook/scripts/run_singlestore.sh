#!/bin/bash

# Check if container exists and remove it if it does
if [ "$(docker ps -aq -f name=singlestoredb)" ]; then
    echo "Removing existing singlestoredb container..."
    docker rm -f singlestoredb
fi

# Start fresh container
echo "Starting SingleStore container..."
docker run -d --name singlestoredb \
  --platform linux/amd64 \
  -p 3306:3306 \
  -p 8080:8080 \
  -v /tmp:/var/lib/memsql \
  -e ROOT_PASSWORD=admin \
  -e LICENSE_KEY=accept \
  ghcr.io/singlestore-labs/singlestoredb-dev:latest

# Wait for SingleStore to be ready
echo "Waiting for SingleStore to be ready..."
sleep 10

# Create database with proper charset
echo "Creating AGNO database with UTF-8 charset..."
docker exec singlestoredb memsql -u root -padmin -e "CREATE DATABASE IF NOT EXISTS AGNO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

echo "Database setup complete!"

export SINGLESTORE_HOST="localhost"
export SINGLESTORE_PORT="3306"
export SINGLESTORE_USERNAME="root"
export SINGLESTORE_PASSWORD="admin"
export SINGLESTORE_DATABASE="AGNO"
