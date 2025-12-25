from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class UserProfile(BaseModel):
    """User identity (reduced for Claude compatibility)"""

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, description="User's name")
    role: Optional[str] = Field(None, description="Job title or role")
    company: Optional[str] = Field(None, description="Company or organization")
    skills: Optional[List[str]] = Field(None, description="Technical skills")


class UserPolicies(BaseModel):
    """User preferences"""

    model_config = ConfigDict(extra="forbid")

    response_style: Optional[str] = Field(None, description="concise/detailed/balanced")
    tone: Optional[str] = Field(None, description="formal/casual/technical")
    include_code_examples: Optional[bool] = Field(None, description="Include code examples")


class UserKnowledge(BaseModel):
    """User context"""

    model_config = ConfigDict(extra="forbid")

    current_project: Optional[str] = Field(None, description="Current project")
    tech_stack: Optional[List[str]] = Field(None, description="Technologies used")
    domain: Optional[str] = Field(None, description="Industry or domain")


class UserFeedback(BaseModel):
    """Response feedback"""

    model_config = ConfigDict(extra="forbid")

    positive: List[str] = Field(default_factory=list, description="What user liked")
    negative: List[str] = Field(default_factory=list, description="What user disliked")
