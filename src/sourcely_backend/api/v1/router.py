from fastapi import APIRouter
from .endpoints import auth, analysis

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(analysis.router, prefix="/code", tags=["analyze"])