"""Integration tests for the Memory routes in AgentOS."""


def test_create_memory(test_os_client):
    """Test creating a new memory."""
    response = test_os_client.post(
        "/memories",
        json={
            "memory": "User prefers technical explanations with code examples",
            "user_id": "test-user-123",
            "topics": ["preferences", "communication_style"],
        },
    )
    assert response.status_code == 200

    response_json = response.json()
    assert response_json["memory_id"] is not None
    assert response_json["memory"] == "User prefers technical explanations with code examples"
    assert response_json["user_id"] == "test-user-123"
    assert set(response_json["topics"]) == {"preferences", "communication_style"}
    assert response_json["updated_at"] is not None


def test_update_memory(test_os_client):
    """Test updating an existing memory."""
    # First create a memory
    create_response = test_os_client.post(
        "/memories",
        json={
            "memory": "Original memory content",
            "user_id": "test-user-update",
            "topics": ["original"],
        },
    )
    memory_id = create_response.json()["memory_id"]

    # Update the memory
    response = test_os_client.patch(
        f"/memories/{memory_id}",
        json={
            "memory": "Updated memory content",
            "user_id": "test-user-update",
            "topics": ["updated", "modified"],
        },
    )
    assert response.status_code == 200

    response_json = response.json()
    assert response_json["memory_id"] == memory_id
    assert response_json["memory"] == "Updated memory content"
    assert set(response_json["topics"]) == {"updated", "modified"}


def test_create_memory_without_user_id_returns_400(test_os_client):
    """Test that creating a memory without user_id returns 400 error."""
    response = test_os_client.post(
        "/memories",
        json={
            "memory": "Some memory content",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "User ID is required"


def test_get_memory_by_id(test_os_client):
    """Test retrieving a specific memory by ID."""
    # First create a memory
    create_response = test_os_client.post(
        "/memories",
        json={
            "memory": "User is a Python developer",
            "user_id": "test-user-789",
            "topics": ["technical", "skills"],
        },
    )
    memory_id = create_response.json()["memory_id"]

    # Now retrieve it
    response = test_os_client.get(f"/memories/{memory_id}")
    assert response.status_code == 200

    response_json = response.json()
    assert response_json["memory_id"] == memory_id
    assert response_json["memory"] == "User is a Python developer"
    assert response_json["user_id"] == "test-user-789"
    assert set(response_json["topics"]) == {"technical", "skills"}


def test_get_memory_with_invalid_id_returns_404(test_os_client):
    """Test retrieving a non-existent memory returns 404."""
    response = test_os_client.get("/memories/invalid-memory-id")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_list_memories(test_os_client):
    """Test listing memories with pagination."""
    # Create multiple memories
    test_os_client.post(
        "/memories",
        json={
            "memory": "Memory 1",
            "user_id": "test-user-list",
            "topics": ["topic1"],
        },
    )
    test_os_client.post(
        "/memories",
        json={
            "memory": "Memory 2",
            "user_id": "test-user-list",
            "topics": ["topic2"],
        },
    )

    # List memories
    response = test_os_client.get("/memories")
    assert response.status_code == 200

    response_json = response.json()
    assert "data" in response_json
    assert "meta" in response_json
    assert len(response_json["data"]) >= 2
    assert response_json["meta"]["page"] == 1
    assert response_json["meta"]["limit"] == 20


def test_list_memories_with_pagination(test_os_client):
    """Test listing memories with custom pagination parameters."""
    # Create test memories
    for i in range(5):
        test_os_client.post(
            "/memories",
            json={
                "memory": f"Memory {i}",
                "user_id": "test-user-pagination",
            },
        )

    # Test pagination
    response = test_os_client.get("/memories?limit=2&page=1")
    assert response.status_code == 200

    response_json = response.json()
    assert len(response_json["data"]) <= 2
    assert response_json["meta"]["limit"] == 2
    assert response_json["meta"]["page"] == 1


def test_list_memories_filtered_by_user(test_os_client):
    """Test filtering memories by user_id."""
    # Create memories for different users
    test_os_client.post(
        "/memories",
        json={
            "memory": "User A memory",
            "user_id": "user-a",
        },
    )
    test_os_client.post(
        "/memories",
        json={
            "memory": "User B memory",
            "user_id": "user-b",
        },
    )

    # Filter by user_id
    response = test_os_client.get("/memories?user_id=user-a")
    assert response.status_code == 200

    response_json = response.json()
    assert all(mem["user_id"] == "user-a" for mem in response_json["data"])


def test_list_memories_filtered_by_topics(test_os_client):
    """Test filtering memories by topics."""
    # Create memories with different topics
    test_os_client.post(
        "/memories",
        json={
            "memory": "Technical memory",
            "user_id": "test-user-topics",
            "topics": ["technical", "python"],
        },
    )
    test_os_client.post(
        "/memories",
        json={
            "memory": "Personal memory",
            "user_id": "test-user-topics",
            "topics": ["personal", "hobbies"],
        },
    )

    # Filter by topic
    response = test_os_client.get("/memories?topics=technical")
    assert response.status_code == 200

    response_json = response.json()
    # Note: The filtering should work, but the exact matching behavior depends on implementation
    assert len(response_json["data"]) >= 1


def test_list_memories_with_search_content(test_os_client):
    """Test searching memories by content."""
    # Create memories with specific content
    test_os_client.post(
        "/memories",
        json={
            "memory": "User loves programming in Python",
            "user_id": "test-user-search",
        },
    )
    test_os_client.post(
        "/memories",
        json={
            "memory": "User prefers Java for enterprise applications",
            "user_id": "test-user-search",
        },
    )

    # Search for specific content
    response = test_os_client.get("/memories?search_content=Python")
    assert response.status_code == 200

    response_json = response.json()
    # At least one result should match
    assert len(response_json["data"]) >= 1


def test_update_memory_without_user_id_returns_400(test_os_client):
    """Test that updating a memory without user_id returns 400 error."""
    response = test_os_client.patch(
        "/memories/some-id",
        json={
            "memory": "Updated content",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "User ID is required"


def test_delete_memory(test_os_client):
    """Test deleting a specific memory."""
    # First create a memory
    create_response = test_os_client.post(
        "/memories",
        json={
            "memory": "Memory to be deleted",
            "user_id": "test-user-delete",
        },
    )
    memory_id = create_response.json()["memory_id"]

    # Delete the memory
    response = test_os_client.delete(f"/memories/{memory_id}")
    assert response.status_code == 204

    # Verify it's deleted by trying to retrieve it
    get_response = test_os_client.get(f"/memories/{memory_id}")
    assert get_response.status_code == 404


def test_delete_multiple_memories(test_os_client):
    """Test deleting multiple memories at once."""
    # Create multiple memories
    memory_ids = []
    for i in range(3):
        create_response = test_os_client.post(
            "/memories",
            json={
                "memory": f"Memory to delete {i}",
                "user_id": "test-user-bulk-delete",
            },
        )
        memory_ids.append(create_response.json()["memory_id"])

    # Delete multiple memories
    response = test_os_client.request(
        "DELETE",
        "/memories",
        json={
            "memory_ids": memory_ids,
            "user_id": "test-user-bulk-delete",
        },
    )
    assert response.status_code == 204

    # Verify they're all deleted
    for memory_id in memory_ids:
        get_response = test_os_client.get(f"/memories/{memory_id}")
        assert get_response.status_code == 404


def test_delete_memories_with_empty_list_returns_422(test_os_client):
    """Test that deleting with empty memory_ids list returns validation error."""
    response = test_os_client.request(
        "DELETE",
        "/memories",
        json={
            "memory_ids": [],
        },
    )
    assert response.status_code == 422
