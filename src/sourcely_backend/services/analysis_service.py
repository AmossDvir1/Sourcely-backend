from datetime import datetime, timezone
from ..schemas.analysis import AnalysisCreate
from ..core.db import analyses
from bson import ObjectId


async def create_analysis(analysis_data: AnalysisCreate, user_id: str) -> dict:
    """
    Saves a new analysis document to the MongoDB 'analyses' collection.

    Args:
        analysis_data: A Pydantic model with the analysis details.
        user_id: The string representation of the user's ObjectId.

    Returns:
        The newly inserted dictionary object from the database.
    """
    # Convert the Pydantic model to a dictionary
    analysis_doc = analysis_data.model_dump()

    # Add the user ID and the current timestamp
    analysis_doc["user_id"] = ObjectId(user_id)
    analysis_doc["analysisDate"] = datetime.now(timezone.utc)

    # Insert the document into the collection
    result = await analyses.insert_one(analysis_doc)

    # Retrieve and return the newly created document
    new_analysis = await analyses.find_one({"_id": result.inserted_id})
    return new_analysis


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
