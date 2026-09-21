import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.exceptions import ComponentRehydrationError
from agno.fs import FileSystem
from agno.fs.local import LocalFileSystem
from agno.fs.toolkit import FileSystemTools
from agno.os.routers.registry import get_registry_router
from agno.registry import Registry


@pytest.fixture
def store(tmp_path):
    return FileSystem(LocalFileSystem(root=tmp_path), namespace="users/{user_id}", max_file_bytes=2048)


def test_registry_references_preserve_policy_and_round_trip(store):
    readonly = store.tools(read_only=True, add_instructions=True)
    registry = Registry(filesystems={"notes": store, "handbook": readonly})
    refs = [{"registry_id": "notes"}, {"registry_id": "handbook"}]

    agent = Agent.from_dict({"id": "writer", "filesystem": refs}, registry=registry, strict=True)
    restored = Agent.from_dict(agent.to_dict(), registry=registry, strict=True)

    assert restored.to_dict()["filesystem"] == refs
    assert restored.filesystems[0][0].backend is store.backend
    assert restored.filesystems[0][0]._raw_namespace == "users/{user_id}"
    assert restored.filesystems[0][0].max_file_bytes == 2048
    assert restored.filesystems[1][1] is True
    toolkit = restored.filesystem[1]
    assert isinstance(toolkit, FileSystemTools)
    assert "write_file" not in toolkit.get_functions()
    assert store._registry_id is None
    assert readonly._registry_id is None


@pytest.mark.asyncio
async def test_async_registry_lookup_and_single_reference(store):
    registry = Registry(filesystems={"notes": store})
    filesystem = await registry.aget_filesystem("notes")

    assert filesystem is not store
    assert Agent(filesystem=filesystem).to_dict()["filesystem"] == {"registry_id": "notes"}
    assert await registry.aget_filesystem("missing") is None


@pytest.mark.parametrize("registry", [None, Registry()])
def test_missing_registry_filesystem_fails_strict_restore(registry):
    with pytest.raises(ComponentRehydrationError, match="filesystem.*not found"):
        Agent.from_dict({"filesystem": {"registry_id": "missing"}}, registry=registry, strict=True)


def test_reference_cannot_override_read_only_policy(store):
    registry = Registry(filesystems={"handbook": store.tools(read_only=True)})
    with pytest.raises(ComponentRehydrationError, match="settings must be configured in the registry"):
        Agent.from_dict(
            {"filesystem": {"registry_id": "handbook", "tools": {"read_only": False}}},
            registry=registry,
            strict=True,
        )


def test_registry_listing_exposes_metadata_without_local_root(store):
    app = FastAPI()
    app.include_router(get_registry_router(Registry(filesystems={"handbook": store.tools(read_only=True)})))

    response = TestClient(app).get("/registry", params={"resource_type": "filesystem"})

    assert response.status_code == 200
    resource = response.json()["data"][0]
    assert resource["id"] == resource["name"] == "handbook"
    assert resource["type"] == "filesystem"
    assert resource["metadata"]["read_only"] is True
    assert resource["metadata"]["namespace"] == "users/{user_id}"
    assert "root" not in resource["metadata"]
    assert str(store.backend.root) not in response.text
