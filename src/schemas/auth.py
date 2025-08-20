from pydantic import BaseModel, EmailStr, Field, field_validator, ConfigDict
from bson import ObjectId
from typing import Optional

# ====================================================================
#  USER OUTPUT MODEL
# ====================================================================
class UserOut(BaseModel):
    """
    A Pydantic model for representing a user, ready for API responses.
    This now includes the optional firstName and lastName fields.
    """
    # The `alias` tells Pydantic to look for `_id` in the input data.
    id: str = Field(..., alias="_id")
    email: EmailStr

    # --- CHANGE 1: ADD OPTIONAL NAME FIELDS ---
    # We add `Optional` and set a default of `None`.
    # Pydantic will now correctly handle users who haven't set their name yet.
    firstName: Optional[str] = Field(None, alias="firstName")
    lastName: Optional[str] = Field(None, alias="lastName")

    # This validator correctly handles the ObjectId -> str conversion.
    # No changes are needed here.
    @field_validator('id', mode='before')
    def validate_object_id(cls, v: any) -> str:
        if isinstance(v, ObjectId):
            return str(v)
        return v

    # Configure the model's behavior. No changes needed here.
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
    )

# ====================================================================
#  USER UPDATE MODEL (NEW)
# ====================================================================
class UserUpdate(BaseModel):
    """
    --- CHANGE 2: ADD NEW MODEL FOR PROFILE UPDATES ---
    This model defines the data that the frontend settings page
    will send to the server when saving a user's profile.
    """
    firstName: str
    lastName: str


# ====================================================================
#  USER INPUT MODEL
# ====================================================================
class UserIn(BaseModel):
    """
    Model for user registration and login.
    No changes are needed here.
    """
    email: EmailStr
    password: str