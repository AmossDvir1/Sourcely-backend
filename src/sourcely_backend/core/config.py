from pydantic_settings import BaseSettings, SettingsConfigDict

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

    # This tells Pydantic to load the variables from a file named ".env"
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8"
    )

# Create a single, importable instance of the settings.
# The rest of your application will import this `settings` object.
settings = Settings()