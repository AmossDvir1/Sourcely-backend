from motor.motor_asyncio import AsyncIOMotorClient
from .config import settings

client = AsyncIOMotorClient(settings.MONGO_URI)
db = client[settings.DB_NAME]

users = db.get_collection("users")
tokens = db.get_collection("refresh_tokens")

async def init_db():
    await users.create_index("email", unique=True)
    await tokens.create_index("token", unique=True)
    # ✅ Notice the clean access and automatic type conversion
    await tokens.create_index(
        "created",
        expireAfterSeconds=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
    )