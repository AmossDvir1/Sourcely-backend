from datetime import datetime, timedelta, timezone
from typing import Optional

from passlib.context import CryptContext
from jose import jwt, JWTError
from fastapi import HTTPException, Depends, Header
from fastapi.security import OAuth2PasswordBearer
from bson import ObjectId
from ..core.config import settings
from ..core.db import users, tokens

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login")

SECRET = settings.JWT_SECRET


def hash_password(pw: str) -> str:
    return pwd_context.hash(pw)


def verify_password(plain, hashed) -> bool:
    return pwd_context.verify(plain, hashed)


def create_token(subject: str, expires_delta: timedelta, type: str):
    to_encode = {"sub": subject, "type": type, "exp": datetime.now(timezone.utc) + expires_delta}
    return jwt.encode(to_encode, SECRET, algorithm="HS256")


async def authenticate_user(email: str, password: str):
    user = await users.find_one({"email": email})
    if not user or not verify_password(password, user["password"]):
        return None
    return user


async def save_refresh_token(user_id: str, token: str):
    await tokens.insert_one({"user_id": user_id, "token": token, "created": datetime.now(timezone.utc)})


async def revoke_refresh_token(token: str):
    await tokens.delete_one({"token": token})


async def validate_refresh_token(token: str):
    record = await tokens.find_one({"token": token})
    if not record:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    try:
        payload = jwt.decode(token, SECRET, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    return payload


async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET, algorithms=["HS256"])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Wrong token type")

        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")

        user = await users.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return user
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")


# Dependency for optional authentication
async def get_optional_current_user(authorization: Optional[str] = Header(None)) -> Optional[dict]:
    """
    Dependency to optionally get a user from an 'Authorization: Bearer <token>' header.
    Does not raise an error if the header is missing or the token is invalid.
    Returns the user document or None.
    """
    if not authorization:
        return None  # No header provided

    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            return None # Invalid scheme
    except ValueError:
        return None # Header is not in 'Bearer <token>' format

    try:
        payload = jwt.decode(token, SECRET, algorithms=["HS256"])
        if payload.get("type") != "access":
            return None  # Not an access token

        user_id = payload.get("sub")
        if not user_id:
            return None  # Invalid payload

        user = await users.find_one({"_id": ObjectId(user_id)})
        # This will return the user if found, or None if not found in DB
        return user
    except (JWTError, HTTPException, ValueError, Exception):
        # If any error occurs during decoding or validation, it's not a valid session.
        return None
