import os
from dotenv import load_dotenv

load_dotenv(".env")

# Then override with local values (if exists)
load_dotenv(".env.local", override=True)

from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """
    Manages all application settings.
    Loads variables from a .env file and validates their types.
    """
    # By using type hints, Pydantic automatically validates and converts the values.
    # If a required variable (one without a default) is missing, the app will
    # fail to start with a clear error message.

    # Database Settings
    MONGO_URI: str
    DB_NAME: str

    # JWT Authentication Settings
    JWT_SECRET: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30  # Default value if not in .env
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7     # Default value

    # Google Gemini API Settings
    GEMINI_API_KEY: str
    GITHUB_ACCESS_TOKEN: str

# Create a single, importable instance of the settings.
# The rest of your application will import this `settings` object.
settings = Settings()