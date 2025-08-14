from typing import Optional

from fastapi import HTTPException, status

from datetime import datetime, timezone
from ..schemas.analysis import AnalysisCreate
from ..core.db import analyses
from bson import ObjectId


# Renamed from create_analysis and logic updated to "claim" a staged analysis.
async def claim_and_save_analysis(analysis_data: AnalysisCreate, user_id: str) -> dict:
    """
    Claims a staged analysis by associating it with a user and making it permanent.
    """
    staged_id = ObjectId(analysis_data.tempId)

    # Find the staged analysis
    staged_analysis = await analyses.find_one({"_id": staged_id, "user_id": None})
    if not staged_analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Staged analysis not found or already claimed."
        )

    # Update the document with the user's ID and provided details
    update_data = {
        "$set": {
            "user_id": ObjectId(user_id),
            "name": analysis_data.name,
            "description": analysis_data.description
        }
    }
    await analyses.update_one({"_id": staged_id}, update_data)

    # Return the updated, now permanent, analysis
    claimed_analysis = await analyses.find_one({"_id": staged_id})
    return claimed_analysis


# Function to stage an analysis from an anonymous or authenticated user
async def stage_analysis(repo_url: str, model_used: str, analysis_content: str, source_code: str, user_id: Optional[str] = None) -> dict:
    """
    Saves a new analysis in a temporary "staged" state.
    It has no user_id, so the TTL index will apply.
    """
    analysis_doc = {
        "user_id": ObjectId(user_id) if user_id else None,
        "name": "Staged Analysis", # Placeholder name
        "description": None,
        "repository": repo_url,
        "modelUsed": model_used,
        "analysisContent": analysis_content,
        "sourceCode": source_code,
        "analysisDate": datetime.now(timezone.utc)
    }
    result = await analyses.insert_one(analysis_doc)
    new_analysis = await analyses.find_one({"_id": result.inserted_id})
    return new_analysis


# Service function to get any analysis by its ID
async def get_analysis_by_id(analysis_id: str) -> dict:
    """
    Retrieves a single analysis from the database by its ID.
    Can be a staged or a permanent analysis.
    """
    analysis = await analyses.find_one({"_id": ObjectId(analysis_id)})
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found.")
    return analysis


async def get_analyses_by_user(user_id: str) -> list[dict]:
    """
    Retrieves all analyses for a specific user from the database,
    sorted with the most recent first.

    Args:
        user_id: The string representation of the user's ObjectId.

    Returns:
        A list of analysis documents belonging to the user.
    """
    # Find all documents where the 'user_id' field matches.
    cursor = analyses.find({"user_id": ObjectId(user_id)})

    # Sort the results by 'analysisDate' in descending order (newest first).
    # The -1 indicates descending order.
    cursor.sort("analysisDate", -1)

    # Convert the cursor to a list of dictionaries.
    # length=None ensures all matching documents are returned.
    return await cursor.to_list(length=None)
