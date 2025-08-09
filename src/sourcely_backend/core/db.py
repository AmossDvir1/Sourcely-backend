from motor.motor_asyncio import AsyncIOMotorClient
from .config import settings
from bson import ObjectId # Import ObjectId

client = AsyncIOMotorClient(settings.MONGO_URI)
db = client[settings.DB_NAME]

users = db.get_collection("users")
tokens = db.get_collection("refresh_tokens")
# ✅ 1. DEFINE THE NEW COLLECTION
analyses = db.get_collection("analyses")

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