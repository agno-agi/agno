# Async MongoDB Integration

Examples demonstrating asynchronous MongoDB integration with Agno agents, teams, and workflows.

## Setup

```shell
uv pip install pymongo motor
```

Run a local MongoDB server using:
```bash
docker run -d \
  --name local-mongo \
  -p 27017:27017 \
  -e MONGO_INITDB_ROOT_USERNAME=mongoadmin \
  -e MONGO_INITDB_ROOT_PASSWORD=secret \
  mongo
```
or use our script:
```bash
./scripts/run_mongodb.sh
```

## Examples

- [`async_mongodb_for_agent.py`](async_mongodb_for_agent.py) - Agent with AsyncMongoDb storage
- [`async_mongodb_for_team.py`](async_mongodb_for_team.py) - Team with AsyncMongoDb storage
- [`async_mongodb_for_workflow.py`](async_mongodb_for_workflow.py) - Workflow with AsyncMongoDb storage
