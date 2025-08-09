from pydantic import BaseModel, EmailStr, Field, field_validator, ConfigDict
from datetime import datetime
from bson import ObjectId
from typing import List, Optional


# This schema is used when CREATING a new analysis via the API
# It will be the body of your POST request. This is correct as is.
class AnalysisCreate(BaseModel):
    name: str
    description: str | None = None
    repository: str
    modelUsed: str
    analysisContent: str


class AnalysisOut(AnalysisCreate):
    """
    Pydantic model for returning a saved analysis from the database.
    Handles the conversion of MongoDB's `_id` to a string `id`.
    """
    id: str = Field(..., alias="_id")
    user_id: str
    analysisDate: datetime

    @field_validator('id', 'user_id', mode='before')
    def validate_object_id(cls, v: any) -> str:
        if isinstance(v, ObjectId):
            return str(v)
        return v

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        arbitrary_types_allowed=True # Important for ObjectId
    )


class AIModel(BaseModel):
    id: str
    name: str
    description: str


class AnalyzeRequest(BaseModel):
    githubUrl: str
    modelId: str
    includedExtensions: Optional[List[str]] = None
    contentTypes: Optional[List[str]] = None


class AnalysisResponse(BaseModel):
    analysis: str
    sourceCode: str


class RepoFilesRequest(BaseModel):
    githubUrl: str


class RepoFilesResponse(BaseModel):
    extensions: List[str]
