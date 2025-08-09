import uvicorn
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

from .core.db import init_db
from .api.v1.router import api_router

app = FastAPI(title="Sourcely Backend")


origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,       # or ["*"] for all
    allow_credentials=True,      # needed for cookies
    allow_methods=["*"],         # allow POST, GET, OPTIONS, etc.
    allow_headers=["*"],         # allow custom headers like Authorization
)

@app.on_event("startup")
async def on_startup():
    # creates the collections & indexes if they don't already exist
    await init_db()
    print("✅ MongoDB collections & indexes are ready")

app.include_router(api_router, prefix="/api/v1")

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=3001
    )
