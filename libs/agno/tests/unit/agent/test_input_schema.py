from typing import List, Optional, TypedDict

import pytest
from pydantic import BaseModel, ConfigDict, Field

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.utils.agent import validate_input


# TypedDict schemas
class ResearchTopicDict(TypedDict):
    topic: str
    focus_areas: List[str]
    target_audience: str
    sources_required: int


class OptionalFieldsDict(TypedDict, total=False):
    topic: str
    focus_areas: List[str]
    priority: Optional[str]


# Pydantic schemas
class ResearchTopic(BaseModel):
    """Structured research topic with specific requirements"""

    topic: str
    focus_areas: List[str] = Field(description="Specific areas to focus on")
    target_audience: str = Field(description="Who this research is for")
    sources_required: int = Field(description="Number of sources needed", default=5)


class OptionalResearchTopic(BaseModel):
    """Research topic with optional fields"""

    topic: str
    focus_areas: List[str] = Field(description="Specific areas to focus on")
    target_audience: Optional[str] = None
    sources_required: int = Field(default=3, description="Number of sources needed")
    priority: Optional[str] = Field(default=None, description="Priority level")


class StrictResearchTopic(BaseModel):
    """Strict research topic with validation"""

    model_config = ConfigDict(extra="forbid")  # Forbid extra fields

    topic: str = Field(min_length=1, max_length=100)
    focus_areas: List[str] = Field(min_items=1, max_items=5)
    target_audience: str = Field(min_length=1)
    sources_required: int = Field(gt=0, le=20)  # Greater than 0, less than or equal to 20


# Fixtures
@pytest.fixture
def typed_dict_agent():
    """Create an agent with TypedDict input schema for testing."""
    return Agent(
        name="Test Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        input_schema=ResearchTopicDict,
    )


@pytest.fixture
def optional_fields_agent():
    """Create an agent with optional fields TypedDict schema."""
    return Agent(
        name="Optional Fields Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        input_schema=OptionalFieldsDict,
    )


@pytest.fixture
def pydantic_agent():
    """Create an agent with Pydantic input schema for testing."""
    return Agent(
        name="Pydantic Test Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        input_schema=ResearchTopic,
    )


@pytest.fixture
def optional_pydantic_agent():
    """Create an agent with optional Pydantic fields."""
    return Agent(
        name="Optional Pydantic Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        input_schema=OptionalResearchTopic,
    )


@pytest.fixture
def strict_pydantic_agent():
    """Create an agent with strict Pydantic validation."""
    return Agent(
        name="Strict Pydantic Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        input_schema=StrictResearchTopic,
    )


# TypedDict tests
def test_typed_dict_agent_validate_input_with_valid_data(typed_dict_agent):
    """Test agent input validation with valid TypedDict data."""
    valid_input = {
        "topic": "AI Research",
        "focus_areas": ["Machine Learning", "NLP"],
        "target_audience": "Developers",
        "sources_required": 5,
    }

    result = validate_input(valid_input)
    assert result == valid_input


def test_typed_dict_agent_validate_input_with_missing_required_field(typed_dict_agent):
    """Test agent input validation fails with missing required fields."""
    invalid_input = {
        "topic": "AI Research",
        # Missing focus_areas, target_audience, sources_required
    }

    with pytest.raises(ValueError, match="Missing required fields"):
        validate_input(invalid_input, typed_dict_agent.input_schema)


def test_typed_dict_agent_validate_input_with_unexpected_field(typed_dict_agent):
    """Test agent input validation fails with unexpected fields."""
    invalid_input = {
        "topic": "AI Research",
        "focus_areas": ["Machine Learning"],
        "target_audience": "Developers",
        "sources_required": 5,
        "unexpected_field": "value",
    }

    with pytest.raises(ValueError, match="Unexpected fields"):
        validate_input(invalid_input, typed_dict_agent.input_schema)


def test_typed_dict_agent_validate_input_with_wrong_type(typed_dict_agent):
    """Test agent input validation fails with wrong field types."""
    invalid_input = {
        "topic": "AI Research",
        "focus_areas": "Not a list",  # Should be List[str]
        "target_audience": "Developers",
        "sources_required": 5,
    }

    with pytest.raises(ValueError, match="expected type"):
        validate_input(invalid_input, typed_dict_agent.input_schema)


def test_typed_dict_agent_validate_input_with_optional_fields(optional_fields_agent):
    """Test agent input validation with optional fields."""
    # Minimal input (only required fields)
    minimal_input = {"topic": "Blockchain", "focus_areas": ["DeFi", "Smart Contracts"]}

    # Input with optional field
    full_input = {"topic": "Blockchain", "focus_areas": ["DeFi", "Smart Contracts"], "priority": "high"}

    # Both should validate successfully
    result1 = validate_input(minimal_input, optional_fields_agent.input_schema)
    result2 = validate_input(full_input, optional_fields_agent.input_schema)

    assert result1 == minimal_input
    assert result2 == full_input


def test_agent_without_input_schema_handles_dict():
    """Test that agent without input_schema handles dict input gracefully."""
    agent = Agent(
        name="No Schema Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        # No input_schema
    )

    dict_input = {"arbitrary": "data", "numbers": [1, 2, 3]}

    # Should not raise an exception and return input unchanged
    result = validate_input(dict_input, agent.input_schema)
    assert result == dict_input


# Pydantic tests
def test_pydantic_agent_validate_input_with_valid_dict(pydantic_agent):
    """Test agent input validation with valid dict that matches Pydantic schema."""
    valid_input = {
        "topic": "AI Research",
        "focus_areas": ["Machine Learning", "NLP"],
        "target_audience": "Developers",
        "sources_required": 8,
    }

    result = validate_input(valid_input, pydantic_agent.input_schema)

    # Result should be a ResearchTopic instance
    assert isinstance(result, ResearchTopic)
    assert result.topic == "AI Research"
    assert result.focus_areas == ["Machine Learning", "NLP"]
    assert result.target_audience == "Developers"
    assert result.sources_required == 8


def test_pydantic_agent_validate_input_with_model_instance(pydantic_agent):
    """Test agent input validation with direct Pydantic model instance."""
    model_instance = ResearchTopic(
        topic="Blockchain",
        focus_areas=["DeFi", "Smart Contracts"],
        target_audience="Crypto Developers",
        sources_required=6,
    )

    result = validate_input(model_instance, pydantic_agent.input_schema)

    # Should return the same instance
    assert result is model_instance
    assert isinstance(result, ResearchTopic)


def test_pydantic_agent_validate_input_with_default_values(pydantic_agent):
    """Test agent input validation uses Pydantic default values."""
    input_without_sources = {
        "topic": "Machine Learning",
        "focus_areas": ["Neural Networks"],
        "target_audience": "Students",
        # sources_required omitted - should use default value of 5
    }

    result = validate_input(input_without_sources, pydantic_agent.input_schema)

    assert isinstance(result, ResearchTopic)
    assert result.sources_required == 5  # Default value


def test_pydantic_agent_validate_input_with_missing_required_field(pydantic_agent):
    """Test agent input validation fails with missing required fields."""
    invalid_input = {
        "topic": "AI Research",
        # Missing focus_areas and target_audience (required fields)
        "sources_required": 5,
    }

    with pytest.raises(ValueError, match="Failed to parse dict into ResearchTopic"):
        validate_input(invalid_input, pydantic_agent.input_schema)


def test_pydantic_agent_validate_input_with_wrong_type(pydantic_agent):
    """Test agent input validation fails with wrong field types."""
    invalid_input = {
        "topic": "AI Research",
        "focus_areas": "Not a list",  # Should be List[str]
        "target_audience": "Developers",
        "sources_required": 5,
    }

    with pytest.raises(ValueError, match="Failed to parse dict into ResearchTopic"):
        validate_input(invalid_input, pydantic_agent.input_schema)


def test_pydantic_agent_validate_input_with_type_coercion(pydantic_agent):
    """Test that Pydantic performs type coercion when possible."""
    input_with_coercion = {
        "topic": "AI Research",
        "focus_areas": ["Machine Learning"],
        "target_audience": "Developers",
        "sources_required": "5",  # String that can be converted to int
    }

    result = validate_input(input_with_coercion, pydantic_agent.input_schema)

    assert isinstance(result, ResearchTopic)
    assert result.sources_required == 5  # Should be converted to int
    assert isinstance(result.sources_required, int)


def test_pydantic_agent_validate_input_with_optional_fields(optional_pydantic_agent):
    """Test agent input validation with optional Pydantic fields."""
    # Minimal input (only required fields)
    minimal_input = {
        "topic": "Blockchain",
        "focus_areas": ["DeFi"],
        # target_audience and sources_required are optional
    }

    result = validate_input(minimal_input, optional_pydantic_agent.input_schema)

    assert isinstance(result, OptionalResearchTopic)
    assert result.topic == "Blockchain"
    assert result.focus_areas == ["DeFi"]
    assert result.target_audience is None
    assert result.sources_required == 3  # Default value
    assert result.priority is None


def test_pydantic_agent_validate_input_with_all_optional_fields(optional_pydantic_agent):
    """Test agent input validation with all optional fields provided."""
    full_input = {
        "topic": "Blockchain",
        "focus_areas": ["DeFi", "Smart Contracts"],
        "target_audience": "Crypto Developers",
        "sources_required": 10,
        "priority": "high",
    }

    result = validate_input(full_input, optional_pydantic_agent.input_schema)

    assert isinstance(result, OptionalResearchTopic)
    assert result.priority == "high"
    assert result.target_audience == "Crypto Developers"
    assert result.sources_required == 10


def test_pydantic_agent_validate_input_with_strict_validation(strict_pydantic_agent):
    """Test agent with strict Pydantic validation rules."""
    valid_input = {
        "topic": "AI Research",
        "focus_areas": ["Machine Learning", "NLP"],
        "target_audience": "Developers",
        "sources_required": 5,
    }

    result = validate_input(valid_input, strict_pydantic_agent.input_schema)
    assert isinstance(result, StrictResearchTopic)


def test_pydantic_agent_validate_input_strict_validation_failures(strict_pydantic_agent):
    """Test various strict validation failures."""

    # Test empty topic (violates min_length=1)
    with pytest.raises(ValueError):
        validate_input(
            {"topic": "", "focus_areas": ["ML"], "target_audience": "Developers", "sources_required": 5},
            strict_pydantic_agent.input_schema,
        )

    # Test too many focus areas (violates max_items=5)
    with pytest.raises(ValueError):
        validate_input(
            {
                "topic": "AI",
                "focus_areas": ["ML", "NLP", "CV", "RL", "DL", "Extra"],  # 6 items > max 5
                "target_audience": "Developers",
                "sources_required": 5,
            },
            strict_pydantic_agent.input_schema,
        )

    # Test sources_required = 0 (violates gt=0)
    with pytest.raises(ValueError):
        validate_input(
            {
                "topic": "AI",
                "focus_areas": ["ML"],
                "target_audience": "Developers",
                "sources_required": 0,  # Should be > 0
            },
            strict_pydantic_agent.input_schema,
        )

    # Test sources_required > 20 (violates le=20)
    with pytest.raises(ValueError):
        validate_input(
            {
                "topic": "AI",
                "focus_areas": ["ML"],
                "target_audience": "Developers",
                "sources_required": 25,  # Should be <= 20
            },
            strict_pydantic_agent.input_schema,
        )


def test_pydantic_agent_validate_input_forbids_extra_fields(strict_pydantic_agent):
    """Test that strict model forbids extra fields."""
    input_with_extra = {
        "topic": "AI",
        "focus_areas": ["ML"],
        "target_audience": "Developers",
        "sources_required": 5,
        "extra_field": "not allowed",  # Should be forbidden
    }

    with pytest.raises(ValueError, match="Failed to parse dict into StrictResearchTopic"):
        validate_input(input_with_extra, strict_pydantic_agent.input_schema)


def test_pydantic_agent_validate_input_different_model_instance(pydantic_agent):
    """Test agent input validation fails with wrong Pydantic model type."""
    wrong_model = OptionalResearchTopic(topic="Test", focus_areas=["Test"])

    with pytest.raises(ValueError, match="Expected ResearchTopic but got OptionalResearchTopic"):
        validate_input(wrong_model, pydantic_agent.input_schema)


def test_agent_without_input_schema_handles_pydantic_model():
    """Test that agent without input_schema handles Pydantic model input."""
    agent = Agent(
        name="No Schema Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        # No input_schema
    )

    model_instance = ResearchTopic(topic="Test", focus_areas=["Test Area"], target_audience="Test Audience")

    # Should not raise an exception and return input unchanged
    result = validate_input(model_instance, agent.input_schema)
    assert result is model_instance


def test_pydantic_field_descriptions_preserved():
    """Test that Pydantic Field descriptions are preserved in the model."""
    # Check that field info is available (this is how Pydantic stores Field metadata)
    schema = ResearchTopic.model_json_schema()

    assert schema["properties"]["focus_areas"]["description"] == "Specific areas to focus on"
    assert schema["properties"]["target_audience"]["description"] == "Who this research is for"
    assert schema["properties"]["sources_required"]["description"] == "Number of sources needed"
    assert schema["properties"]["sources_required"]["default"] == 5


def test_pydantic_json_serialization():
    """Test that Pydantic models serialize to JSON properly."""
    model = ResearchTopic(topic="AI", focus_areas=["ML", "NLP"], target_audience="Developers", sources_required=7)

    # Test model_dump_json
    json_str = model.model_dump_json(indent=2, exclude_none=True)
    assert isinstance(json_str, str)

    # Parse back and verify
    import json

    parsed = json.loads(json_str)
    assert parsed["topic"] == "AI"
    assert parsed["focus_areas"] == ["ML", "NLP"]
    assert parsed["sources_required"] == 7


def test_pydantic_model_validation_error_messages():
    """Test that Pydantic validation errors contain useful information."""
    agent = Agent(
        name="Test Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        input_schema=ResearchTopic,
    )

    invalid_input = {
        "topic": "AI",
        "focus_areas": "not a list",  # Wrong type
        "target_audience": "Developers",
        # Missing sources_required
    }

    try:
        validate_input(invalid_input, agent.input_schema)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        error_msg = str(e)
        assert "Failed to parse dict into ResearchTopic" in error_msg
        # The original Pydantic error should be included
        assert "validation error" in error_msg or "Input should be" in error_msg
