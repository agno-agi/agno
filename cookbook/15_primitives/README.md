# Agno Entities and Configs

These cookbooks demonstrate how to save and load agents to and from the database.

## Save an agent to the database

```python
agent.save()
```

OR

```python
agent.save(db=db)
```

This function will save the agent to the database and return the version of the agent.

## Load an agent from the database

```python
agent = get_agent_by_id(db=db, id="agno-agent")
```

In order to configure non-serializable components, you can pass in a registry.

```python
agent = get_agent_by_id(db=db, id="agno-agent", registry=registry)
```
