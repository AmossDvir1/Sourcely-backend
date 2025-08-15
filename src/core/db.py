from motor.motor_asyncio import AsyncIOMotorClient
from .config import settings
from datetime import datetime, timezone

client = AsyncIOMotorClient(settings.MONGO_URI)
db = client[settings.DB_NAME]

users = db.get_collection("users")
tokens = db.get_collection("refresh_tokens")
# ✅ 1. DEFINE THE NEW COLLECTION
analyses = db.get_collection("analyses")
chat_chunks = db.get_collection("chat_chunks")
chat_sessions = db.get_collection("chat_sessions")


async def init_db():
    await users.create_index("email", unique=True)
    await tokens.create_index("token", unique=True)
    await tokens.create_index(
        "created",
        expireAfterSeconds=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
    )
    # ✅ 2. CREATE AN INDEX FOR THE ANALYSES COLLECTION
    # This will help quickly find all analyses belonging to a specific user.
    await analyses.create_index("user_id")


    # TTL index for staged analyses.
    # It will delete documents where 'user_id' is null after 24 hours.
    await analyses.create_index(
        "analysisDate",
        expireAfterSeconds=24 * 60 * 60,  # 24 hours
        partialFilterExpression={"user_id": None}
    )

    await chat_sessions.create_index("createdAt", expireAfterSeconds=24 * 60 * 60)
