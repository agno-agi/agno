import enum
from typing import List, Optional

from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.models.zhipu import Zhipu


class MovieScript(BaseModel):
    setting: str = Field(..., description="Provide a nice setting for a blockbuster movie.")
    ending: str = Field(
        ...,
        description="Ending of the movie. If not available, provide a happy ending.",
    )
    genre: str = Field(
        ...,
        description="Genre of the movie. If not available, select action, thriller or romantic comedy.",
    )
    name: str = Field(..., description="Give a name to this movie")
    characters: List[str] = Field(..., description="Name of characters for this movie.")
    storyline: str = Field(..., description="3 sentence storyline for the movie. Make it exciting!")


def test_structured_response():
    """Test basic structured output with MovieScript schema"""
    agent = Agent(
        model=Zhipu(id="glm-4.7"),
        description="You help people write movie scripts",
        output_schema=MovieScript,
    )
    response = agent.run("New York")
    assert response.content is not None
    assert isinstance(response.content, MovieScript)
    assert isinstance(response.content.setting, str)
    assert isinstance(response.content.characters, List)


def test_structured_response_with_enum():
    """Test structured response with enum fields"""

    class Grade(enum.Enum):
        A_PLUS = "a+"
        A = "a"
        B = "b"
        C = "c"

    class Recipe(BaseModel):
        recipe_name: str
        rating: Grade

    agent = Agent(
        model=Zhipu(id="glm-4.7"),
        output_schema=Recipe,
    )
    response = agent.run("Generate a recipe name and rating")
    assert response.content is not None
    assert isinstance(response.content.rating, Grade)


def test_structured_response_with_thinking():
    """Test structured response with thinking mode"""
    agent = Agent(
        model=Zhipu(id="glm-4.7", enable_thinking=True),
        output_schema=MovieScript,
    )
    response = agent.run("Create a sci-fi movie about time travel")
    assert response.content is not None
    assert isinstance(response.content, MovieScript)
    assert len(response.content.storyline) > 20


def test_nested_structured_response():
    """Test nested structured responses"""

    class Actor(BaseModel):
        name: str
        role: str

    class Movie(BaseModel):
        title: str
        year: int
        main_actors: List[Actor]

    agent = Agent(
        model=Zhipu(id="glm-4.7"),
        output_schema=Movie,
    )

    response = agent.run("Tell me about Inception (2010)")
    assert response.content is not None
    assert isinstance(response.content, Movie)
    assert isinstance(response.content.main_actors, list)
    assert len(response.content.main_actors) > 0


def test_structured_response_with_optional_and_complex_types():
    """Test structured response with optional fields and complex types"""
    from typing import Dict, Optional, Union

    class Product(BaseModel):
        name: str
        price: Optional[float] = None
        tags: List[str]
        metadata: Dict[str, Union[str, int]] = Field(default_factory=dict)

    agent = Agent(
        model=Zhipu(id="glm-4.7"),
        output_schema=Product,
    )

    response = agent.run("Tell me about iPhone 15")
    assert response.content is not None
    assert isinstance(response.content, Product)
    assert response.content.name is not None
    assert isinstance(response.content.tags, list)
    assert isinstance(response.content.metadata, dict)


def test_complex_nested_schema_strict_comparison():
    """
    Test that strict=False (Zhipu default) successfully handles complex nested schemas.
    This includes 4-level nesting with lists, dicts, and optional fields.
    """
    from typing import Dict, Optional

    # 4-level nested structure
    class Address(BaseModel):
        street: str
        city: str
        country: str
        postal_code: Optional[str] = None

    class ContactInfo(BaseModel):
        email: str
        phone: str
        address: Address

    class Project(BaseModel):
        name: str
        budget: float

    class Department(BaseModel):
        name: str
        head: str
        projects: List[Project]

    class Employee(BaseModel):
        name: str
        age: int
        contact: ContactInfo
        department: Department
        skills: List[str]
        metadata: Dict[str, str] = Field(default_factory=dict)

    agent = Agent(
        model=Zhipu(id="glm-4.7"),  # Uses default strict_output=False
        output_schema=Employee,
    )

    response = agent.run(
        "Create employee profile: John Doe, 35, Software Engineer in AI Department led by Alice, "
        "working on ChatBot and ML Pipeline projects, lives in San Francisco"
    )

    # Verify complex nested structure is properly parsed
    assert response.content is not None
    assert isinstance(response.content, Employee)
    assert response.content.name is not None
    assert isinstance(response.content.contact, ContactInfo)
    assert isinstance(response.content.contact.address, Address)
    assert isinstance(response.content.department, Department)
    assert isinstance(response.content.department.projects, list)
    assert len(response.content.department.projects) > 0
    assert isinstance(response.content.skills, list)


def test_strict_mode_with_deeply_nested_schema():
    """
    Test that strict=False succeeds while strict=True fails on complex nested schemas.
    This demonstrates why Zhipu uses strict_output=False as default.

    The test uses a highly complex schema that typically causes strict mode failures:
    - Multiple nesting levels (4 deep)
    - Lists of objects
    - Dictionary fields
    - Multiple required fields at each level
    """
    from typing import Dict

    # Design a complex schema that will stress the strict mode
    class DatabaseConfig(BaseModel):
        host: str
        port: int
        username: str
        password: str
        max_connections: int
        timeout_seconds: int

    class CacheConfig(BaseModel):
        enabled: bool
        ttl_seconds: Optional[int] = None
        max_size_mb: int
        strategy: str

    class ServiceEndpoint(BaseModel):
        path: str
        method: str
        rate_limit: int
        cache: CacheConfig
        database: DatabaseConfig
        metadata: Dict[str, str]

    class MicroserviceConfig(BaseModel):
        service_name: str
        version: Optional[str]
        endpoints: List[ServiceEndpoint]
        global_settings: Dict[str, str]
        feature_flags: Dict[str, bool]

    # Test 1: strict=False - should succeed
    agent_flexible = Agent(
        model=Zhipu(id="glm-4.7"),
        output_schema=MicroserviceConfig,
    )

    response_flexible = agent_flexible.run(
        "Create config for UserService v2.0 with 2 endpoints: "
        "GET /users (rate limit 1000, cache enabled 60s 100MB redis, db: localhost:5432 user/pass max 50 connections 30s timeout) "
        "and POST /users (rate limit 100, cache disabled, same db). "
        "Global: env=prod, region=us-east. Features: new_ui=true, beta=false"
    )

    # Print messages sent to the model
    print("\n" + "=" * 80)
    print("Messages sent to model:")
    print("=" * 80)
    for i, msg in enumerate(response_flexible.messages or []):
        print(f"\n[Message {i + 1}] Role: {msg.role}")
        print("-" * 80)
        print(msg.content if isinstance(msg.content, str) else str(msg.content)[:10000])
    print("=" * 80 + "\n")

    # Verify strict=False succeeds
    assert response_flexible.content is not None
    assert isinstance(response_flexible.content, MicroserviceConfig)
    assert len(response_flexible.content.endpoints) >= 2
    assert all(isinstance(e, ServiceEndpoint) for e in response_flexible.content.endpoints)
    assert all(isinstance(e.cache, CacheConfig) for e in response_flexible.content.endpoints)
    assert all(isinstance(e.database, DatabaseConfig) for e in response_flexible.content.endpoints)

    # Test 2: strict=True - should fail or produce incomplete/invalid results
    agent_strict = Agent(
        model=Zhipu(id="glm-4.7", strict_output=True),
        output_schema=MicroserviceConfig,
    )

    response_strict = agent_strict.run(
        "Create config for UserService v2.0 with 2 endpoints: "
        "GET /users (rate limit 1000, cache enabled 60s 100MB redis, db: localhost:5432 user/pass max 50 connections 30s timeout) "
        "and POST /users (rate limit 100, cache disabled, same db). "
        "Global: env=prod, region=us-east. Features: new_ui=true, beta=false"
    )

    # If we get here, check if the result is actually valid
    # strict=True often produces incomplete nested structures
    if response_strict.content is None:
        assert False, "strict=True produced None content"

    # Check if nested structures are incomplete
    has_valid_endpoints = (
        isinstance(response_strict.content, MicroserviceConfig)
        and len(response_strict.content.endpoints) >= 2
        and all(isinstance(e.cache, CacheConfig) for e in response_strict.content.endpoints)
        and all(isinstance(e.database, DatabaseConfig) for e in response_strict.content.endpoints)
    )
    assert has_valid_endpoints is True
