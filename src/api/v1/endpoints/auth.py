from fastapi import APIRouter, Response, Cookie, HTTPException, Depends
from datetime import timedelta

from ....core.config import settings
from ....core.db import users
from ....schemas.auth import UserIn, UserOut, UserUpdate
from ....schemas.token import AccessTokenOnly
from ....services.auth_service import hash_password, create_token, save_refresh_token, \
    authenticate_user, validate_refresh_token, revoke_refresh_token, get_current_user

router = APIRouter()

ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS = settings.REFRESH_TOKEN_EXPIRE_DAYS


@router.post("/register", response_model=AccessTokenOnly)
async def register_and_login(data: UserIn, response: Response):
    # 1) Prevent duplicate email
    if await users.find_one({"email": data.email}):
        raise HTTPException(400, "Email already registered")

    # 2) Hash & insert user
    hashed = hash_password(data.password)
    result = await users.insert_one({"email": data.email, "password": hashed})
    user_id = str(result.inserted_id)  # ← define user_id here

    # 3) Generate tokens
    access_token = create_token(user_id, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES), "access")
    refresh_token = create_token(user_id, timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS), "refresh")

    # 4) Persist refresh token
    await save_refresh_token(user_id, refresh_token)

    # 5) Set HttpOnly, Secure cookie for the refresh token
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,          # MUST be True for SameSite=None
        samesite="none",      # The fix for cross-origin cookie sending
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
    )

    return AccessTokenOnly(access_token=access_token)


@router.post("/login", response_model=AccessTokenOnly)
async def login(data: UserIn, response: Response):
    user = await authenticate_user(data.email, data.password)
    if not user:
        raise HTTPException(401, "Invalid credentials")
    user_id = str(user["_id"])

    access_token = create_token(user_id, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES), "access")
    refresh_token = create_token(user_id, timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS), "refresh")
    await save_refresh_token(user_id, refresh_token)

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,          # MUST be True for SameSite=None
        samesite="none",      # The fix for cross-origin cookie sending
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
    )

    return AccessTokenOnly(access_token=access_token)


@router.post("/refresh", response_model=AccessTokenOnly)
async def refresh(response: Response, refresh_token: str = Cookie(None)):
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Missing refresh token cookie")

    # Validate & decode the existing refresh token
    payload = await validate_refresh_token(refresh_token)
    user_id = payload["sub"]  # ← pull user_id from payload

    # Rotate tokens
    await revoke_refresh_token(refresh_token)
    new_refresh = create_token(user_id, timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS), "refresh")
    await save_refresh_token(user_id, new_refresh)
    new_access = create_token(user_id, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES), "access")

    # Update the cookie
    response.set_cookie(
        key="refresh_token",
        value=new_refresh,
        httponly=True,
        secure=True,          # MUST be True for SameSite=None
        samesite="none",      # The fix for cross-origin cookie sending
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
    )

    return AccessTokenOnly(access_token=new_access)


@router.post("/logout")
async def logout(
        response: Response,
        # This dependency protects the route. The code won't run if the access token is invalid.
        current_user: dict = Depends(get_current_user),
        # We still need the refresh token from the cookie to revoke it.
        refresh_token: str = Cookie(None)
):
    """
    Logs out the authenticated user.

    This is a protected endpoint. It requires a valid access token.
    It revokes the refresh token found in the HttpOnly cookie.
    """
    if not refresh_token:
        # This case is unlikely if the user is authenticated, but it's good practice.
        raise HTTPException(status_code=400, detail="No refresh token cookie found to invalidate")

    # The user is authenticated, and we have the refresh token. Proceed with logout.
    # You could even add a log here for auditing purposes.
    print(f"User {current_user['email']} is logging out.")

    # 1. Invalidate the long-lived refresh token in the database.
    await revoke_refresh_token(refresh_token)

    # 2. Clear the cookie from the user's browser to complete the process.
    response.delete_cookie("refresh_token")

    return {"msg": "Successfully logged out"}


@router.get("/verify", response_model=UserOut)
async def verify_token(current_user: dict = Depends(get_current_user)):
    """
    Verifies the access token provided in the Authorization header.

    If the token is valid, returns a 200 OK with the user's email.
    If the token is invalid, expired, or missing, the `get_current_user`
    dependency will automatically raise a 401 Unauthorized HTTPException.
    """
    return current_user


@router.put("/users/me", response_model=UserOut)
async def update_current_user(
        user_data: UserUpdate,
        current_user: dict = Depends(get_current_user)
):
    """
    Updates the profile information for the currently authenticated user.
    """
    user_id = current_user["_id"]

    update_data = {
        "$set": {
            "firstName": user_data.firstName,
            "lastName": user_data.lastName
        }
    }

    # Find the user by ID and update their document
    await users.update_one({"_id": user_id}, update_data)

    # Fetch the updated user document to return it
    updated_user = await users.find_one({"_id": user_id})

    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found after update")

    return updated_user