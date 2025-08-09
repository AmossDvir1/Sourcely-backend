import os
from fastapi import APIRouter, Depends, HTTPException
from google import genai
from google.genai import types

from ....core.config import settings

from ....schemas.analysis import AnalyzeRequest, AIModel, AnalysisResponse
from ....services import github_service
from ....services.auth_service import get_current_user

router = APIRouter()


try:
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
except KeyError:
    # This provides a clear error if the .env file is not set up correctly
    raise RuntimeError("GEMINI_API_KEY not found in environment variables.") from None


def get_real_models() -> list[dict]:
    """
    Fetches models from the Google GenAI API and filters for those
    that can be used for generative content analysis.
    """
    real_models = []
    for model in client.models.list():
        print(model, "\n")
        # We only want models that can actually generate content for our analysis
        if 'generateContent' in model.supported_actions:
            real_models.append({
                "id": model.name or "No id available.",  # e.g., "models/gemini-1.5-pro-latest"
                "name": model.display_name or "No name available.", # e.g., "Gemini 1.5 Pro"
                "description": model.description or "No description available."
            })
    return real_models


@router.get("/models", response_model=list[AIModel])
async def get_available_models(current_user: dict = Depends(get_current_user)):
    """
    Returns a list of available AI models for analysis from the Google GenAI API.
    """
    try:
        models_list = get_real_models()
        return models_list
    except Exception as e:
        # If the Google API call fails for any reason (e.g., invalid key, network issue)
        print(f"Error fetching models from Google API: {e}")
        raise HTTPException(status_code=500, detail="Could not retrieve AI models from the provider.")


@router.post("/analyze", response_model=AnalysisResponse)
async def analyze(data: AnalyzeRequest, current_user: dict = Depends(get_current_user)):
    """
    Accepts a GitHub URL and a model ID, fetches the repository content,
    formats it, and sends it to the Google GenAI API for analysis.
    """
    # === Step 1: Validate the chosen model (same as before) ===
    available_models = get_real_models()
    valid_model_ids = {model['id'] for model in available_models}
    if data.modelId not in valid_model_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid modelId '{data.modelId}'. Please use a valid model."
        )

    # === Step 2: Fetch and prepare repository data using the service ===
    try:
        print(f"User {current_user['email']} starting analysis of: {data.githubUrl}")
        # Call our new service to get all relevant files and their content.
        # The service will raise its own exceptions on failure.
        repo_files = await github_service.get_repo_contents_from_url(data.githubUrl)

        if not repo_files:
            raise HTTPException(
                status_code=400,
                detail="Could not find any relevant source code files to analyze in the repository."
            )

        # Format the fetched data into a single, clean string for the LLM prompt.
        formatted_content = ""
        for path, content in repo_files.items():
            formatted_content += f"--- FILE: {path} ---\n"
            formatted_content += f"{content}\n\n"

        print(f"Total characters to analyze: {len(formatted_content)}")

    except ValueError as e:
        # Handles user-facing errors like an invalid URL or a 404 Not Found.
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # Handles unexpected server-side errors during fetching.
        print(f"An unexpected error occurred during repository fetching: {e}")
        raise HTTPException(status_code=500, detail="An internal error occurred while fetching repository data.")

    # === Step 3: Send the formatted content to the Google GenAI API ===
    try:
        print(f"Sending request to Google GenAI with model: {data.modelId}")
        # Initialize the specific generative model the user chose.
        #model = genai.GenerativeModel(data.modelId)

        # This is the prompt that instructs the AI on what to do.
        # This is the most important part to get right for a good analysis!
        prompt = f"""
        You are an expert software developer and code analyst.
        Analyze the following collection of source code files from a GitHub repository.
        Provide a concise, high-level summary of the project.

        Your analysis should include:
        1.  **Project Purpose:** What is this project designed to do?
        2.  **Key Technologies:** What are the main languages, frameworks, and libraries used?
        3.  **Architecture Overview:** Briefly describe the project structure and how the different parts might interact.
        4.  **Potential Improvements or Areas of Interest:** Point out one or two interesting things, or suggest a potential improvement.

        Here is the source code:
        {formatted_content}
        """

        # Generate the content based on the prompt.
        response = client.models.generate_content(
            model=data.modelId, contents=prompt
        )

        # Return the AI's generated text in the correct response format.
        return {"analysis": response.text}

    except Exception as e:
        # Handle errors from the Google API (e.g., API key issue, content filtering).
        print(f"An error occurred with the Google GenAI API: {e}")
        raise HTTPException(status_code=503,
                            detail="The AI service is currently unavailable or failed to process the request.")
