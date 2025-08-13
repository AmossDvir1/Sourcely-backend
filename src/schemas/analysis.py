from pydantic import BaseModel, Field, field_validator, ConfigDict
from datetime import datetime
from bson import ObjectId
from typing import List, Optional


# This schema is used when CREATING a new analysis via the API
# It will be the body of your POST request. This is correct as is.
class AnalysisCreate(BaseModel):
    name: str
    description: Optional[str] = None
    tempId: str  # The unique ID of the staged analysis to be claimed.
    # Note: We no longer pass repository, modelUsed, or analysisContent here.
    # The backend will use the tempId to find the existing staged record.



# ==============================================================================
# 2. OUTPUT SCHEMA for representing an analysis from the database.
#    This is used by GET /analyses and GET /analyses/{id}.
# ==============================================================================
class AnalysisOut(BaseModel):
    id: str = Field(..., alias="_id")
    user_id: Optional[str] = None  # Can be null for a staged analysis
    name: str
    description: Optional[str] = None
    repository: str
    modelUsed: str
    analysisContent: str
    analysisDate: datetime
    # Note: Does NOT include 'sourceCode' by default to keep API responses light.
    # The full source can be fetched separately if needed.

    # This validator correctly handles the conversion of MongoDB's ObjectId
    # to a string for both 'id' and 'user_id'.
    @field_validator('id', 'user_id', mode='before')
    def validate_object_id(cls, v: any) -> str:
        if v is None:
            return None
        if isinstance(v, ObjectId):
            return str(v)
        return v

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        arbitrary_types_allowed=True,
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
    tempId: str # This is crucial for redirecting the user


class RepoFilesRequest(BaseModel):
    githubUrl: str


class RepoFilesResponse(BaseModel):
    extensions: List[str]
    repoName: str
