from typing import Optional

from fastapi import HTTPException, status

from datetime import datetime, timezone
from ..schemas.analysis import AnalysisCreate
from ..core.db import analyses
from bson import ObjectId


async def save_or_claim_analysis(analysis_data: AnalysisCreate, user_id: str) -> dict:
    """
    Saves an analysis for a user.
    - If a valid tempId is provided, it "claims" the staged analysis.
    - If the tempId is missing or invalid (e.g., deleted), it creates a new analysis record.
    """
    staged_analysis = None
    if analysis_data.tempId:
        try:
            staged_id = ObjectId(analysis_data.tempId)
            staged_analysis = await analyses.find_one({"_id": staged_id, "user_id": None})
        except Exception:
            # tempId is not a valid ObjectId, so we can't find it.
            staged_analysis = None

    if staged_analysis:
        # --- SCENARIO 1: CLAIMING (tempId was valid) ---
        print(f"Claiming staged analysis {analysis_data.tempId} for user {user_id}")
        update_data = {
            "$set": {
                "user_id": ObjectId(user_id),
                "name": analysis_data.name,
                "description": analysis_data.description
            }
        }
        await analyses.update_one({"_id": staged_analysis["_id"]}, update_data)
        saved_analysis = await analyses.find_one({"_id": staged_analysis["_id"]})
        # We need to return the new ID for the frontend to use
        saved_analysis["_id"] = str(saved_analysis["_id"])
        return saved_analysis
    else:
        # --- SCENARIO 2: CREATING (tempId was missing, invalid, or already used/deleted) ---
        print(f"Creating new analysis '{analysis_data.name}' for user {user_id}")
        new_analysis_doc = {
            "user_id": ObjectId(user_id),
            "name": analysis_data.name,
            "description": analysis_data.description,
            "repository": analysis_data.repository,
            "modelUsed": analysis_data.modelUsed,
            "analysisContent": analysis_data.analysisContent,
            "analysisDate": datetime.now(timezone.utc)
        }
        result = await analyses.insert_one(new_analysis_doc)
        new_analysis = await analyses.find_one({"_id": result.inserted_id})
        # Return the new ID
        new_analysis["_id"] = str(new_analysis["_id"])
        return new_analysis


# Function to stage an analysis from an anonymous or authenticated user
async def stage_analysis(repo_url: str, model_used: str, analysis_content: str,  user_id: Optional[str] = None) -> dict:
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


async def delete_analysis(analysis_id: str, user_id: str):
    """
    Deletes a single analysis from the database, ensuring ownership.
    """
    result = await analyses.delete_one({
        "_id": ObjectId(analysis_id),
        "user_id": ObjectId(user_id)  # SECURITY: Ensures the user owns this analysis
    })

    # If nothing was deleted, it means the analysis either didn't exist
    # or didn't belong to the user.
    if result.deleted_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis not found or you do not have permission to delete it."
        )