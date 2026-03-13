import os
import tempfile

import pytest

from agno.context.manager import ContextManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat


@pytest.fixture
def temp_db_file():
    """Create a temporary SQLite database file for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as temp_file:
        db_path = temp_file.name

    yield db_path

    # Clean up the temporary file after the test
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def context_db(temp_db_file):
    """Create a SQLite context database for testing."""
    db = SqliteDb(db_file=temp_db_file)
    return db


@pytest.fixture
def model():
    """Create an OpenAI model for testing."""
    return OpenAIChat(id="gpt-4o-mini")


@pytest.fixture
def context_manager_with_db(model, context_db):
    """Create a ContextManager instance with database connections."""
    return ContextManager(model=model, db=context_db)


def test_create_context_item_with_db(context_manager_with_db):
    """Test creating a context item with database persistence."""
    # Create a basic context item
    item_id = context_manager_with_db.create(
        name="test_prompt",
        content="Hello {name_var}, you are a {role}",
    )

    # Verify item was created
    assert item_id is not None
    assert isinstance(item_id, str)

    # Retrieve and verify content with variables
    result = context_manager_with_db.get(name="test_prompt", name_var="World", role="assistant")
    assert result == "Hello World, you are a assistant"


def test_create_with_all_parameters(context_manager_with_db):
    """Test creating context item with all optional parameters."""
    # Create item with all parameters
    item_id = context_manager_with_db.create(
        name="full_params",
        content="Content with {var}",
        description="Test description",
        metadata={"type": "greeting", "version": 1},
        version=2,
        parent_id="parent-123",
        optimization_notes="Test notes",
    )

    # Verify all fields were stored
    items = context_manager_with_db.list()
    item = [i for i in items if i.id == item_id][0]
    assert item.name == "full_params"
    assert item.description == "Test description"
    assert item.metadata == {"type": "greeting", "version": 1}
    assert item.version == 2
    assert item.parent_id == "parent-123"


def test_create_extracts_variables(context_manager_with_db):
    """Test that create automatically extracts variables from content."""
    # Create item with multiple variables
    item_id = context_manager_with_db.create(
        name="vars_test",
        content="Hello {user_name}, you are {age} years old and work as {role}",
    )

    # Verify variables were extracted
    items = context_manager_with_db.list()
    item = [i for i in items if i.id == item_id][0]
    assert set(item.variables) == {"user_name", "age", "role"}


def test_create_multiple_items_same_name(context_manager_with_db):
    """Test creating multiple items with same name but different metadata."""
    # Create multiple items with same name
    id1 = context_manager_with_db.create(name="multi", content="Dev", metadata={"env": "dev"})
    id2 = context_manager_with_db.create(name="multi", content="Prod", metadata={"env": "prod"})
    id3 = context_manager_with_db.create(name="multi", content="Test", metadata={"env": "test"})

    # Verify all items exist with unique IDs
    items = context_manager_with_db.list()
    multi_items = [i for i in items if i.name == "multi"]
    assert len(multi_items) == 3
    assert id1 != id2 != id3


def test_create_persistence_across_instances(model, context_db):
    """Test that created items persist across different ContextManager instances."""
    # Create first instance and add item
    context1 = ContextManager(model=model, db=context_db)
    context1.create(name="persistent", content="Test {var}")

    # Create second instance with same database
    context2 = ContextManager(model=model, db=context_db)

    # Verify item persisted
    items = context2.list()
    assert len(items) == 1
    assert items[0].name == "persistent"


def test_get_with_variables(context_manager_with_db):
    """Test retrieving context with variable substitution."""
    # Create item with variables
    context_manager_with_db.create(
        name="greet",
        content="Welcome {user}! Your role is {role}.",
    )

    # Get item with variable substitution
    result = context_manager_with_db.get(name="greet", user="Alice", role="admin")
    assert result == "Welcome Alice! Your role is admin."


def test_get_with_metadata_filter(context_manager_with_db):
    """Test getting context with metadata filtering."""
    # Create multiple items with same name, different metadata
    context_manager_with_db.create(name="multi", content="Dev {x}", metadata={"env": "dev"})
    context_manager_with_db.create(name="multi", content="Prod {x}", metadata={"env": "prod"})

    # Get with metadata filter
    dev_result = context_manager_with_db.get(name="multi", metadata={"env": "dev"}, x="test")
    assert dev_result == "Dev test"

    prod_result = context_manager_with_db.get(name="multi", metadata={"env": "prod"}, x="test")
    assert prod_result == "Prod test"


def test_get_nonexistent_raises_error(context_manager_with_db):
    """Test that getting non-existent item raises ValueError."""
    with pytest.raises(ValueError, match="not found"):
        context_manager_with_db.get(name="nonexistent")


def test_get_with_wrong_metadata_raises_error(context_manager_with_db):
    """Test that getting with wrong metadata raises ValueError."""
    # Create item with metadata
    context_manager_with_db.create(name="test", content="test", metadata={"env": "dev"})

    # Try to get with different metadata
    with pytest.raises(ValueError, match="not found"):
        context_manager_with_db.get(name="test", metadata={"env": "prod"})


def test_get_without_variables_in_non_strict_mode():
    """Test getting content without providing all variables in non-strict mode."""
    # Create context manager without strict mode
    context = ContextManager()
    context.create(name="partial", content="{a} {b} {c}")

    # Get without all variables - should leave unprovided variables as placeholders
    result = context.get(name="partial", a="1", c="3")
    assert "1" in result
    assert "{b}" in result
    assert "3" in result


def test_get_strict_mode_missing_variables_raises_error():
    """Test that strict mode raises error when variables are missing."""
    # Create context manager with strict mode
    context = ContextManager(strict_mode=True)
    context.create(name="strict", content="Hello {user_name}, you are {age}")

    # Should succeed with all variables
    result = context.get(name="strict", user_name="John", age=30)
    assert result == "Hello John, you are 30"

    # Should fail with missing variables
    with pytest.raises(ValueError, match="Missing required variables"):
        context.get(name="strict", user_name="John")


def test_get_with_extra_variables(context_manager_with_db):
    """Test that extra variables are ignored."""
    # Create simple item
    context_manager_with_db.create(name="simple", content="Hello {user_name}")

    # Get with extra variables
    result = context_manager_with_db.get(name="simple", user_name="World", extra="ignored", another="also_ignored")
    assert result == "Hello World"


def test_get_with_extra_variables_strict(context_manager_with_db):
    """Test that extra variables are ignored."""
    # Create simple item
    context_strict = ContextManager(strict_mode=True)
    context_strict.create(name="simple", content="Hello {user_name}")

    # Get with extra variables
    result = context_strict.get(name="simple", user_name="World", extra="ignored", another="also_ignored")
    assert result == "Hello World"


def test_update_operations(context_manager_with_db):
    """Test various update operations on context items."""
    # Test 1: Update content only
    context_manager_with_db.create(name="updatable", content="Original {var}")
    context_manager_with_db.update(name="updatable", content="Updated {var}")
    result = context_manager_with_db.get(name="updatable", var="test")
    assert result == "Updated test"

    # Test 2: Update description
    context_manager_with_db.create(name="desc_test", content="content", description="Original")
    context_manager_with_db.update(name="desc_test", description="Updated description")
    items = context_manager_with_db.list()
    item = [i for i in items if i.name == "desc_test"][0]
    assert item.description == "Updated description"

    # Test 3: Update metadata
    context_manager_with_db.create(name="meta_test", content="content", metadata={"v": 1})
    context_manager_with_db.update(name="meta_test", new_metadata={"v": 2, "updated": True})
    items = context_manager_with_db.list()
    item = [i for i in items if i.name == "meta_test"][0]
    assert item.metadata == {"v": 2, "updated": True}

    # Test 4: Update with metadata filter (target specific item when multiple have same name)
    context_manager_with_db.create(name="multi", content="Dev", metadata={"env": "dev"})
    context_manager_with_db.create(name="multi", content="Prod", metadata={"env": "prod"})
    context_manager_with_db.update(name="multi", metadata={"env": "dev"}, content="Updated Dev")
    dev_result = context_manager_with_db.get(name="multi", metadata={"env": "dev"})
    prod_result = context_manager_with_db.get(name="multi", metadata={"env": "prod"})
    assert dev_result == "Updated Dev"
    assert prod_result == "Prod"

    # Test 5: Update multiple fields at once
    context_manager_with_db.create(name="multi_update", content="Original", description="Old desc", version=1)
    context_manager_with_db.update(
        name="multi_update",
        content="New content {x}",
        description="New desc",
        new_metadata={"updated": True},
        version=5,
    )
    items = context_manager_with_db.list()
    item = [i for i in items if i.name == "multi_update"][0]
    assert item.version == 5
    assert item.description == "New desc"
    assert item.metadata == {"updated": True}


def test_update_nonexistent_raises_error(context_manager_with_db):
    """Test that updating non-existent item raises ValueError."""
    with pytest.raises(ValueError, match="not found"):
        context_manager_with_db.update(name="nonexistent", content="new")


def test_update_updates_variables(context_manager_with_db):
    """Test that updating content also updates extracted variables."""
    # Create item with one variable
    context_manager_with_db.create(name="var_update", content="Hello {user_name}")

    # Update with more variables
    context_manager_with_db.update(name="var_update", content="Hello {user_name}, you are {age}")

    # Verify variables were updated
    items = context_manager_with_db.list()
    item = [i for i in items if i.name == "var_update"][0]
    assert set(item.variables) == {"user_name", "age"}


def test_delete_operations(context_manager_with_db):
    """Test various delete operations on context items."""
    # Test 1: Delete by name
    context_manager_with_db.create(name="deletable", content="content")
    context_manager_with_db.delete(name="deletable")
    items = context_manager_with_db.list()
    assert len([i for i in items if i.name == "deletable"]) == 0

    # Test 2: Delete with metadata filter (target specific item when multiple have same name)
    context_manager_with_db.create(name="multi_del", content="Dev", metadata={"env": "dev"})
    context_manager_with_db.create(name="multi_del", content="Prod", metadata={"env": "prod"})
    context_manager_with_db.delete(name="multi_del", metadata={"env": "dev"})
    items = context_manager_with_db.list()
    multi_items = [i for i in items if i.name == "multi_del"]
    assert len(multi_items) == 1
    assert multi_items[0].metadata == {"env": "prod"}

    # Test 3: Delete nonexistent raises error
    with pytest.raises(ValueError, match="not found"):
        context_manager_with_db.delete(name="nonexistent")

    # Test 4: Delete with wrong metadata raises error
    context_manager_with_db.create(name="test_meta", content="test", metadata={"env": "dev"})
    with pytest.raises(ValueError, match="not found"):
        context_manager_with_db.delete(name="test_meta", metadata={"env": "prod"})


def test_list_operations(context_manager_with_db):
    """Test various list operations on context items."""
    # Test 1: List empty collection
    items = context_manager_with_db.list()
    assert len(items) == 0

    # Test 2: List all items
    context_manager_with_db.create(name="item1", content="1")
    context_manager_with_db.create(name="item2", content="2")
    context_manager_with_db.create(name="item3", content="3")
    items = context_manager_with_db.list()
    assert len(items) == 3

    # Test 3: List with metadata filter
    context_manager_with_db.clear()
    context_manager_with_db.create(name="item1", content="1", metadata={"type": "a", "priority": 1})
    context_manager_with_db.create(name="item2", content="2", metadata={"type": "b", "priority": 2})
    context_manager_with_db.create(name="item3", content="3", metadata={"type": "a", "priority": 1})
    filtered = context_manager_with_db.list(metadata={"type": "a", "priority": 1})
    assert len(filtered) == 2

    # Test 4: List with no matching metadata returns empty
    no_match = context_manager_with_db.list(metadata={"type": "c"})
    assert len(no_match) == 0


def test_clear_operations(context_manager_with_db):
    """Test clear operations on context items."""
    # Test 1: Clear with items
    for i in range(5):
        context_manager_with_db.create(name=f"item{i}", content=f"Content {i}")
    items = context_manager_with_db.list()
    assert len(items) == 5
    context_manager_with_db.clear()
    items = context_manager_with_db.list()
    assert len(items) == 0

    # Test 2: Clear empty collection (should not error)
    context_manager_with_db.clear()
    items = context_manager_with_db.list()
    assert len(items) == 0


def test_optimize_creates_new_version(context_manager_with_db):
    """Test optimizing creates a new version of the context item."""
    # Create verbose item
    context_manager_with_db.create(
        name="verbose",
        content="You are a {role} who works in {domain}. Your task is to {task}.",
        metadata={"version": "v1"},
    )

    # Optimize and create new version
    optimized = context_manager_with_db.optimize(
        name="verbose",
        metadata={"version": "v1"},
        create_new_version=True,
        new_metadata={"version": "v2", "optimized": True},
    )

    # Verify new version was created
    assert optimized is not None

    items = context_manager_with_db.list()
    assert len(items) == 2

    # Verify both versions exist
    v1_items = context_manager_with_db.list(metadata={"version": "v1"})
    v2_items = context_manager_with_db.list(metadata={"version": "v2", "optimized": True})
    assert len(v1_items) == 1
    assert len(v2_items) == 1


def test_optimize_in_place(context_manager_with_db):
    """Test optimizing updates item in place."""
    # Create item
    context_manager_with_db.create(
        name="optimize_inplace",
        content="Very verbose and redundant prompt that says the same thing repeatedly.",
    )

    # Optimize in place
    optimized = context_manager_with_db.optimize(name="optimize_inplace", create_new_version=False)

    # Verify only one version exists
    assert optimized is not None

    items = context_manager_with_db.list()
    assert len([i for i in items if i.name == "optimize_inplace"]) == 1


def test_optimize_nonexistent_raises_error(context_manager_with_db):
    """Test that optimizing non-existent item raises ValueError."""
    with pytest.raises(ValueError, match="not found"):
        context_manager_with_db.optimize(name="nonexistent")


def test_optimize_with_custom_instructions(context_manager_with_db):
    """Test optimizing with custom optimization instructions."""
    # Create item
    context_manager_with_db.create(name="custom_opt", content="Original prompt")

    # Optimize with custom instructions
    optimized = context_manager_with_db.optimize(
        name="custom_opt",
        optimization_instructions="Make this extremely brief",
        create_new_version=False,
    )

    assert optimized is not None


@pytest.mark.asyncio
async def test_acreate_basic():
    """Test async creation of context item."""
    # Create context manager without database (in-memory async)
    context = ContextManager()

    # Create item asynchronously
    item_id = await context.acreate(
        name="async_item",
        content="Async content {var}",
    )

    assert item_id is not None


@pytest.mark.asyncio
async def test_acreate_with_all_parameters():
    """Test async creation with all parameters."""
    # Create context manager without database (in-memory async)
    context = ContextManager()

    # Create item with all parameters
    item_id = await context.acreate(
        name="async_full",
        content="Content {x}",
        description="Async test",
        metadata={"type": "async"},
        version=3,
    )

    # Verify parameters were stored
    items = await context.alist()
    item = [i for i in items if i.id == item_id][0]
    assert item.metadata == {"type": "async"}
    assert item.version == 3


@pytest.mark.asyncio
async def test_aget_with_variables():
    """Test async retrieval with variable substitution."""
    # Create context manager without database (in-memory async)
    context = ContextManager()

    # Create item
    await context.acreate(name="async_get", content="Hello {user}")

    # Get with variable substitution
    result = await context.aget(name="async_get", user="Async")
    assert result == "Hello Async"


@pytest.mark.asyncio
async def test_aget_with_metadata():
    """Test async retrieval with metadata filter."""
    # Create context manager without database (in-memory async)
    context = ContextManager()

    # Create items with different metadata
    await context.acreate(name="async_meta", content="Dev", metadata={"env": "dev"})
    await context.acreate(name="async_meta", content="Prod", metadata={"env": "prod"})

    # Get with metadata filter
    result = await context.aget(name="async_meta", metadata={"env": "dev"})
    assert result == "Dev"


@pytest.mark.asyncio
async def test_aget_nonexistent_raises_error():
    """Test that async get of non-existent item raises ValueError."""
    # Create context manager without database (in-memory async)
    context = ContextManager()

    with pytest.raises(ValueError, match="not found"):
        await context.aget(name="nonexistent")


@pytest.mark.asyncio
async def test_aupdate_content():
    """Test async update of content."""
    # Create context manager without database (in-memory async)
    context = ContextManager()

    # Create item
    await context.acreate(name="async_update", content="Original")

    # Update content
    await context.aupdate(name="async_update", content="Updated {x}")

    # Verify update
    result = await context.aget(name="async_update", x="test")
    assert result == "Updated test"


@pytest.mark.asyncio
async def test_aupdate_metadata():
    """Test async update of metadata."""
    # Create context manager without database (in-memory async)
    context = ContextManager()

    # Create item with metadata
    await context.acreate(name="async_meta_update", content="content", metadata={"v": 1})

    # Update metadata
    await context.aupdate(name="async_meta_update", new_metadata={"v": 2})

    # Verify metadata was updated
    items = await context.alist()
    item = [i for i in items if i.name == "async_meta_update"][0]
    assert item.metadata == {"v": 2}


@pytest.mark.asyncio
async def test_aupdate_nonexistent_raises_error():
    """Test that async update of non-existent item raises ValueError."""
    # Create context manager without database (in-memory async)
    context = ContextManager()

    with pytest.raises(ValueError, match="not found"):
        await context.aupdate(name="nonexistent", content="new")


@pytest.mark.asyncio
async def test_adelete_by_name():
    """Test async deletion by name."""
    # Create context manager without database (in-memory async)
    context = ContextManager()

    # Create item
    await context.acreate(name="async_delete", content="content")

    # Delete item
    await context.adelete(name="async_delete")

    # Verify deletion
    items = await context.alist()
    assert len([i for i in items if i.name == "async_delete"]) == 0


@pytest.mark.asyncio
async def test_adelete_with_metadata():
    """Test async deletion with metadata filter."""
    # Create context manager without database (in-memory async)
    context = ContextManager()

    # Create multiple items with same name
    await context.acreate(name="async_multi_del", content="Dev", metadata={"env": "dev"})
    await context.acreate(name="async_multi_del", content="Prod", metadata={"env": "prod"})

    # Delete only dev version
    await context.adelete(name="async_multi_del", metadata={"env": "dev"})

    # Verify only dev was deleted
    items = await context.alist()
    multi_items = [i for i in items if i.name == "async_multi_del"]
    assert len(multi_items) == 1
    assert multi_items[0].metadata == {"env": "prod"}


@pytest.mark.asyncio
async def test_adelete_nonexistent_raises_error():
    """Test that async delete of non-existent item raises ValueError."""
    # Create context manager without database (in-memory async)
    context = ContextManager()

    with pytest.raises(ValueError, match="not found"):
        await context.adelete(name="nonexistent")


@pytest.mark.asyncio
async def test_alist_all_items():
    """Test async listing of all items."""
    # Create context manager without database (in-memory async)
    context = ContextManager()

    # Create multiple items
    await context.acreate(name="async1", content="1")
    await context.acreate(name="async2", content="2")
    await context.acreate(name="async3", content="3")

    # List all items
    items = await context.alist()
    assert len(items) == 3


@pytest.mark.asyncio
async def test_alist_with_metadata_filter():
    """Test async listing with metadata filter."""
    # Create context manager without database (in-memory async)
    context = ContextManager()

    # Create items with different metadata
    await context.acreate(name="a1", content="1", metadata={"type": "a"})
    await context.acreate(name="a2", content="2", metadata={"type": "b"})
    await context.acreate(name="a3", content="3", metadata={"type": "a"})

    # List with metadata filter
    filtered = await context.alist(metadata={"type": "a"})
    assert len(filtered) == 2


@pytest.mark.asyncio
async def test_aclear_all_items():
    """Test async clearing of all items."""
    # Create context manager without database (in-memory async)
    context = ContextManager()

    # Create multiple items
    for i in range(5):
        await context.acreate(name=f"async_item{i}", content=f"Content {i}")

    # Verify items exist
    items = await context.alist()
    assert len(items) == 5

    # Clear all items
    await context.aclear()

    # Verify all cleared
    items = await context.alist()
    assert len(items) == 0


@pytest.mark.asyncio
async def test_aoptimize_creates_new_version(model):
    """Test async optimize creates new version."""
    # Create context manager with model (in-memory async)
    context = ContextManager(model=model)

    # Create verbose item
    await context.acreate(
        name="async_opt",
        content="Verbose prompt that could be optimized",
        metadata={"v": 1},
    )

    # Optimize and create new version
    optimized = await context.aoptimize(
        name="async_opt",
        metadata={"v": 1},
        create_new_version=True,
        new_metadata={"v": 2},
    )

    # Verify new version was created
    assert optimized is not None

    items = await context.alist()
    assert len(items) == 2


@pytest.mark.asyncio
async def test_aoptimize_in_place(model):
    """Test async optimize in place."""
    # Create context manager with model (in-memory async)
    context = ContextManager(model=model)

    # Create item
    await context.acreate(name="async_opt_inplace", content="Verbose prompt")

    # Optimize in place
    optimized = await context.aoptimize(name="async_opt_inplace", create_new_version=False)

    # Verify only one version exists
    assert optimized is not None

    items = await context.alist()
    assert len([i for i in items if i.name == "async_opt_inplace"]) == 1


def test_content_edge_cases(context_manager_with_db):
    """Test various content edge cases and special formats."""
    # Test 1: Unicode content
    context_manager_with_db.create(name="unicode", content="你好 {user_name}! Welcome to {place} 🎉")
    result = context_manager_with_db.get(name="unicode", user_name="世界", place="中国")
    assert all(text in result for text in ["你好", "世界", "中国", "🎉"])

    # Test 2: Empty content
    context_manager_with_db.create(name="empty", content="")
    assert context_manager_with_db.get(name="empty") == ""

    # Test 3: Special characters in name
    for name in ["name-with-dashes", "name_with_underscores", "name.with.dots", "path/to/item"]:
        item_id = context_manager_with_db.create(name=name, content="test")
        assert item_id is not None
        assert context_manager_with_db.get(name=name) == "test"

    # Test 4: HTML content
    html = "<div class='{cls}'>{text}</div>"
    context_manager_with_db.create(name="html", content=html)
    result = context_manager_with_db.get(name="html", cls="test", text="Hello")
    assert result == "<div class='test'>Hello</div>"

    # Test 5: JSON-like content
    json_content = '{"user": "{user}", "value": {value}}'
    context_manager_with_db.create(name="json", content=json_content)
    result = context_manager_with_db.get(name="json", user="test", value=123)
    assert '"user": "test"' in result and '"value": 123' in result

    # Test 6: Multiline content
    multiline = """Line 1 with {var1}
    Line 2 with {var2}
    Line 3 with {var3}"""
    context_manager_with_db.create(name="multiline", content=multiline)
    result = context_manager_with_db.get(name="multiline", var1="A", var2="B", var3="C")
    assert all(line in result for line in ["Line 1 with A", "Line 2 with B", "Line 3 with C"])

    # Test 7: Variables with numbers
    context_manager_with_db.create(name="num_vars", content="{var1} {var2} {var123}")
    result = context_manager_with_db.get(name="num_vars", var1="a", var2="b", var123="c")
    assert result == "a b c"

    # Test 8: Repeated variables
    context_manager_with_db.create(name="repeat", content="{x} and {x} and {x}")
    result = context_manager_with_db.get(name="repeat", x="A")
    assert result == "A and A and A"

    # Test 9: Very long content
    long_content = "x" * 10000 + " {var} " + "y" * 10000
    context_manager_with_db.create(name="long", content=long_content)
    result = context_manager_with_db.get(name="long", var="middle")
    assert len(result) > 20000 and "middle" in result


def test_metadata_variations(context_manager_with_db):
    """Test various metadata formats and edge cases."""
    # Test 1: None metadata
    context_manager_with_db.create(name="none_meta", content="test", metadata=None)
    items = context_manager_with_db.list()
    item = [i for i in items if i.name == "none_meta"][0]
    assert item.metadata is None

    # Test 2: Empty dict metadata
    context_manager_with_db.create(name="empty_meta", content="test", metadata={})
    # Empty metadata filter {} matches all items (same as no filter)
    items = context_manager_with_db.list(metadata={})
    assert len(items) == 2  # Both none_meta and empty_meta


def test_version_and_parent_tracking(context_manager_with_db):
    """Test version and parent_id tracking."""
    # Create version chain
    id1 = context_manager_with_db.create(name="v1", content="Version 1", version=1)

    id2 = context_manager_with_db.create(name="v2", content="Version 2", version=2, parent_id=id1)

    id3 = context_manager_with_db.create(name="v3", content="Version 3", version=3, parent_id=id2)

    # Verify parent tracking
    items = context_manager_with_db.list()
    v2_item = [i for i in items if i.id == id2][0]
    v3_item = [i for i in items if i.id == id3][0]

    assert v2_item.parent_id == id1
    assert v3_item.parent_id == id2


def test_in_memory_storage_without_db():
    """Test that ContextManager works without database (in-memory only)."""
    # Create context without database
    context = ContextManager()

    # Create item
    item_id = context.create(name="memory_only", content="Hello {user_name}")
    assert item_id is not None

    # Get item
    result = context.get(name="memory_only", user_name="World")
    assert result == "Hello World"

    # List items
    items = context.list()
    assert len(items) == 1


@pytest.mark.asyncio
async def test_async_in_memory_storage_without_db():
    """Test that async methods work without database."""
    # Create context without database
    context = ContextManager()

    # Create item asynchronously
    item_id = await context.acreate(name="async_memory", content="Test {x}")
    assert item_id is not None

    # Get item asynchronously
    result = await context.aget(name="async_memory", x="value")
    assert result == "Test value"

    # List items asynchronously
    items = await context.alist()
    assert len(items) == 1
