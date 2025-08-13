from pydantic import BaseModel
from datetime import datetime


class TokenPayload(BaseModel):
    sub: str
    exp: datetime


class AccessTokenOnly(BaseModel):
    access_token: str
    token_type: str = "bearer"
