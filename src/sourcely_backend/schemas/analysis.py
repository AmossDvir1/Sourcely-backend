from pydantic import BaseModel


class AIModel(BaseModel):
    id: str
    name: str
    description: str


class AnalyzeRequest(BaseModel):
    githubUrl: str
    modelId: str

class AnalysisResponse(BaseModel):
    analysis: str