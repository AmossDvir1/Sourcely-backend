import os
from fastapi import APIRouter, Depends, HTTPException, status
from google import genai
from typing import Set, Optional

from ....core.config import settings
from ....schemas.analysis import AnalyzeRequest, AIModel, StagedAnalysisResponse, AnalysisCreate, AnalysisOut, \
    RepoFilesResponse, RepoFilesRequest
from ....services import github_service, analysis_service
from ....services.auth_service import get_current_user, get_optional_current_user
from ....services.github_service import _parse_github_url

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
        # print(model, "\n")
        # We only want models that can actually generate content for our analysis
        if 'generateContent' in model.supported_actions:
            real_models.append({
                "id": model.name or "No id available.",  # e.g., "models/gemini-1.5-pro-latest"
                "name": model.display_name or "No name available.",  # e.g., "Gemini 1.5 Pro"
                "description": model.description or "No description available."
            })
    return real_models


@router.get("/models", response_model=list[AIModel])
async def get_available_models():
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


PROMPT_SECTIONS = {
    "General Description": """
1.  **Project Purpose:** What is this project designed to do? Who is the intended user?
2.  **Key Technologies:** What are the main languages, frameworks, and libraries used?""",

    "instructions-file": """
3.  **Setup & Usage:** Based on the files (like README, package.json, requirements.txt), how would a developer set up and run this project?""",

    "Project File Tree": """
4.  **Architecture Overview:** display an ASCII file structure. Make it look good"""
}


@router.post("/analyze", response_model=StagedAnalysisResponse)
async def analyze(data: AnalyzeRequest, current_user: Optional[dict] = Depends(get_optional_current_user)):
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
        user_email = current_user['email'] if current_user else "Anonymous"
        print(f"User {user_email} starting analysis of: {data.githubUrl}")
        # Call our new service to get all relevant files and their content.
        # The service will raise its own exceptions on failure.
        repo_files = await github_service.get_repo_contents_from_url(data.githubUrl)

        if not repo_files:
            raise HTTPException(
                status_code=400,
                detail="Could not find any relevant source code files to analyze in the repository."
            )


    except ValueError as e:
        # Handles user-facing errors like an invalid URL or a 404 Not Found.
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # Handles unexpected server-side errors during fetching.
        print(f"An unexpected error occurred during repository fetching: {e}")
        raise HTTPException(status_code=500, detail="An internal error occurred while fetching repository data.")

    # Check if the user provided a specific list of extensions to include.
    if data.includedExtensions is not None:
        print(f"Applying file mask. Including extensions: {data.includedExtensions}")

        filtered_files = {}
        # Convert list to a set for much faster "in" checks.
        include_set = set(data.includedExtensions)

        for path, content in repo_files.items():
            # Determine the file's "extension" (which could also be a full filename like 'Dockerfile')
            if '.' in path:
                ext = '.' + path.split('.')[-1]
            else:
                ext = path.split('/')[-1]  # Fallback for files with no extension

            # If the file's extension is in our include set, add it to our filtered list.
            if ext in include_set:
                filtered_files[path] = content

        # Overwrite the original repo_files dictionary with our newly filtered one.
        repo_files = filtered_files

        if not repo_files:
            raise HTTPException(
                status_code=400,
                detail="No files matched the selected extension filters. Please select at least one file type."
            )
    else:
        # This branch is taken if `includedExtensions` is null or not provided.
        print("No file mask provided. Analyzing all supported file types.")

    # Determine which sections to include
    requested_sections = data.contentTypes
    if not requested_sections or "All" in requested_sections:
        # If "All" is requested or nothing is specified, use all sections
        sections_to_include = list(PROMPT_SECTIONS.keys())
    else:
        sections_to_include = requested_sections

    # Build the dynamic part of the prompt
    dynamic_prompt_parts = []
    for section_name in sections_to_include:
        if section_name in PROMPT_SECTIONS:
            dynamic_prompt_parts.append(PROMPT_SECTIONS[section_name])

    # Join the selected parts into a single string
    analysis_instructions = "\n".join(dynamic_prompt_parts)

    print(analysis_instructions)

    formatted_content = ""
    for path, content in repo_files.items():
        formatted_content += f"--- FILE: {path} ---\n"
        formatted_content += f"{content}\n\n"

    print(f"Total characters to analyze after filtering: {len(formatted_content)}")

    # This is the prompt that instructs the AI on what to do.
    # This is the most important part to get right for a good analysis!
    prompt = f"""
    You are an expert software developer and code analyst.
    Analyze the following collection of source code files from a GitHub repository.

    Please provide the following analysis based on my selection:
    {analysis_instructions}

    ---
    Here is the source code for your analysis:
    {formatted_content}
    """

    # === Step 3: Send the formatted content to the Google GenAI API ===
    try:

        print(f"Sending request to Google GenAI with model: {data.modelId}")
        # Generate the content based on the prompt.
        response = client.models.generate_content(
            model=data.modelId, contents=prompt
        )
        user_id_str = str(current_user["_id"]) if current_user else None
        staged_analysis = await analysis_service.stage_analysis(
            repo_url=data.githubUrl,
            model_used=data.modelId,
            analysis_content=response.text,
            source_code=formatted_content,
            user_id=user_id_str
        )

        return {"tempId": str(staged_analysis["_id"])}


    except Exception as e:
        # Handle errors from the Google API (e.g., API key issue, content filtering).
        print(f"An error occurred with the Google GenAI API: {e}")
        raise HTTPException(status_code=503,
                            detail="The AI service is currently unavailable or failed to process the request.")


@router.post("/analyses", response_model=AnalysisOut, status_code=status.HTTP_201_CREATED)
async def save_analysis(
        analysis_data: AnalysisCreate,
        current_user: dict = Depends(get_current_user)
):
    """
    Saves a completed AI analysis to the database for the authenticated user.
    """
    try:
        user_id = str(current_user["_id"])
        print(f"User {current_user['email']} is saving an analysis named '{analysis_data.name}'.")

        # Call the new service function to handle the database logic
        saved_analysis = await analysis_service.claim_and_save_analysis(
            analysis_data=analysis_data,
            user_id=user_id
        )
        return saved_analysis
    except Exception as e:
        # Catch any potential database errors
        print(f"Error saving analysis to database: {e}")
        raise HTTPException(status_code=500, detail="Could not save the analysis due to an internal error.")


# NEW: Public endpoint to fetch an analysis by its ID
@router.get("/analyses/{analysis_id}", response_model=AnalysisOut)
async def get_analysis(analysis_id: str):
    """
    Retrieves a single analysis by its ID. Can be a staged or saved analysis.
    This endpoint is public to allow anonymous users to view a result
    before deciding to sign up and save it.
    """
    try:
        analysis = await analysis_service.get_analysis_by_id(analysis_id)
        return analysis
    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"Error fetching analysis {analysis_id}: {e}")
        raise HTTPException(status_code=500, detail="Could not retrieve the analysis.")


@router.post("/prepare-analysis", response_model=RepoFilesResponse)
async def prepare_analysis(data: RepoFilesRequest):
    """
    Fetches the file tree of a repository and returns a unique list of
    file extensions for the user to select from on the frontend.
    """
    try:
        # ✅ 2. Parse the URL to get the owner and repo name first
        owner_repo = _parse_github_url(data.githubUrl)
        if not owner_repo:
            raise ValueError("Invalid GitHub URL format. Could not parse owner and repository.")

        owner, repo = owner_repo
        repo_name = f"{owner}/{repo}"  # Create the clean name string

        print(f"Preparing analysis for {repo_name}")
        repo_files = await github_service.get_repo_contents_from_url(data.githubUrl)

        if not repo_files:
            # ✅ 3. Return the repo name even if no files are found
            return {"extensions": [], "repoName": repo_name}

        # Use a set to automatically handle uniqueness
        unique_extensions: Set[str] = set()
        for path in repo_files.keys():
            if '.' in path:
                ext = '.' + path.split('.')[-1]
                unique_extensions.add(ext)
            else:
                filename = path.split('/')[-1]
                if filename in github_service.SOURCE_CODE_EXTENSIONS:
                    unique_extensions.add(filename)

        # ✅ 4. Include the repoName in the final response
        return {"extensions": sorted(list(unique_extensions)), "repoName": repo_name}

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"An unexpected error occurred during repository preparation: {e}")
        raise HTTPException(status_code=500, detail="An internal error occurred while preparing repository data.")
