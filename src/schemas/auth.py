from pydantic import BaseModel, EmailStr, Field, field_validator, ConfigDict
from bson import ObjectId


class UserOut(BaseModel):
    """
    A Pydantic model for representing a user, ready for API responses.
    """
    # 1. Define the fields with their final desired names and types.
    # The `alias` tells Pydantic to look for `_id` in the input data.
    id: str = Field(..., alias="_id")
    email: EmailStr

    # 2. Add a validator to handle the ObjectId -> str conversion.
    # This runs *before* Pydantic's internal validation, on the raw input.
    @field_validator('id', mode='before')
    def validate_object_id(cls, v: any) -> str:
        if isinstance(v, ObjectId):
            return str(v)
        # If it's already a string (or something else), let it pass through
        # for Pydantic's standard validation to handle.
        return v

    # 3. Configure the model's behavior.
    model_config = ConfigDict(
        # Allows creating the model from a database object (e.g., user["email"])
        from_attributes=True,
        # Allows Pydantic to use the alias (`_id`) when populating the model
        populate_by_name=True,
    )


class UserIn(BaseModel):
    email: EmailStr
    password: str

