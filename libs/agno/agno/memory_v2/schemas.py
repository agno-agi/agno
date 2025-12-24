from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class UserProfile(BaseModel):
    """User identity"""

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, description="User's name")
    company: Optional[str] = Field(None, description="Company or organization")
    role: Optional[str] = Field(None, description="Job title or role")
    location: Optional[str] = Field(None, description="Location or timezone")
    skills: Optional[List[str]] = Field(None, description="Technical skills")
    experience_level: Optional[str] = Field(None, description="junior/mid/senior/staff")
    preferred_name: Optional[str] = Field(None, description="Nickname or preferred name")
    language: Optional[str] = Field(None, description="Preferred language")


class UserPolicies(BaseModel):
    """User preferences"""

    model_config = ConfigDict(extra="forbid")

    response_style: Optional[str] = Field(None, description="concise/detailed/balanced")
    tone: Optional[str] = Field(None, description="formal/casual/technical")
    include_code_examples: Optional[bool] = Field(None, description="Include code")
    use_emojis: Optional[bool] = Field(None, description="Use emojis")
    use_markdown: Optional[bool] = Field(None, description="Format with markdown")


class UserKnowledge(BaseModel):
    """User context"""

    model_config = ConfigDict(extra="forbid")

    current_project: Optional[str] = Field(None, description="Current project")
    tech_stack: Optional[List[str]] = Field(None, description="Technologies used")
    interests: Optional[List[str]] = Field(None, description="Topics of interest")
    domain: Optional[str] = Field(None, description="Industry/domain")


class UserFeedback(BaseModel):
    """Response feedback"""

    model_config = ConfigDict(extra="forbid")

    positive: List[str] = Field(default_factory=list, description="What user liked")
    negative: List[str] = Field(default_factory=list, description="What user disliked")
