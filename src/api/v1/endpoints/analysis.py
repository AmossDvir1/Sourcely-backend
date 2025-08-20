from fastapi import APIRouter, Depends, HTTPException, status, Response
from typing import Set, Optional, List

from ....services.llm_service import get_real_models
from ....services import llm_service

from ....schemas.analysis import AnalyzeRequest, AIModel, StagedAnalysisResponse, AnalysisCreate, AnalysisOut, \
    RepoFilesResponse, RepoFilesRequest
from ....services import github_service, analysis_service
from ....services.auth_service import get_current_user, get_optional_current_user
from ....services.github_service import _parse_github_url

router = APIRouter()


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
    Accepts a GitHub URL, a model ID, and the full repository codebase.
    It formats the content and sends it to the Google GenAI API for analysis,
    then stages the result without saving the source code.
    """
    # === Step 1: Validate the chosen model ===
    available_models = get_real_models()
    valid_model_ids = {model['id'] for model in available_models}
    if data.modelId not in valid_model_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid modelId '{data.modelId}'. Please use a valid model."
        )

    # === Step 2: Use the pre-fetched codebase from the request ===
    # No need to fetch from GitHub here. The codebase is passed directly.
    formatted_content = data.codebase

    if not formatted_content:
        raise HTTPException(
            status_code=400,
            detail="No source code was provided to analyze."
        )

    # Note: File extension filtering is now expected to happen on the frontend
    # before this endpoint is called. The received `codebase` is treated as final.

    # === Step 3: Build the prompt dynamically ===
    requested_sections = data.contentTypes
    if not requested_sections or "All" in requested_sections:
        sections_to_include = list(PROMPT_SECTIONS.keys())
    else:
        sections_to_include = requested_sections

    dynamic_prompt_parts = []
    for section_name in sections_to_include:
        if section_name in PROMPT_SECTIONS:
            dynamic_prompt_parts.append(PROMPT_SECTIONS[section_name])

    analysis_instructions = "\n".join(dynamic_prompt_parts)

    print(f"Total characters to analyze: {len(formatted_content)}")

    prompt = f"""
    You are an expert software developer and code analyst.
    Analyze the following collection of source code files from a GitHub repository.

    Please provide the following analysis based on my selection:
    {analysis_instructions}

    ---
    Here is the source code for your analysis:
    {formatted_content}
    """

    # === Step 4: Send to GenAI and Stage the Analysis (WITHOUT source code) ===
    try:
        user_email = current_user['email'] if current_user else "Anonymous"
        print(f"User {user_email} starting analysis of: {data.githubUrl}")
        print(f"Sending request to Google GenAI with model: {data.modelId}")

        response_text = await llm_service.generate_llm_response(
            prompt=prompt,
            model_id=data.modelId,
            stream=False
        )

        user_id_str = str(current_user["_id"]) if current_user else None

        staged_analysis = await analysis_service.stage_analysis(
            repo_url=data.githubUrl,
            model_used=data.modelId,
            analysis_content=response_text,
            user_id=user_id_str
        )

        return {"tempId": str(staged_analysis["_id"])}

    except Exception as e:
        print(f"An error occurred with the Google GenAI API: {e}")
        raise HTTPException(
            status_code=503,
            detail="The AI service is currently unavailable or failed to process the request."
        )


@router.post("/analyses", response_model=AnalysisOut, status_code=status.HTTP_201_CREATED)
async def save_analysis(
        analysis_data: AnalysisCreate,
        current_user: dict = Depends(get_current_user)
):
    """
    Saves or claims an AI analysis for the authenticated user.
    """
    try:
        user_id = str(current_user["_id"])
        print(f"User {current_user['email']} is saving an analysis named '{analysis_data.name}'.")

        # Use the new resilient service function
        saved_analysis = await analysis_service.save_or_claim_analysis(
            analysis_data=analysis_data,
            user_id=user_id
        )
        return saved_analysis
    except Exception as e:
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


@router.get("/analyses", response_model=List[AnalysisOut])
async def get_user_analyses(current_user: dict = Depends(get_current_user)):
    """
    Retrieves all analyses saved by the currently authenticated user.
    """
    try:
        user_id = str(current_user["_id"])
        user_analyses = await analysis_service.get_analyses_for_user(user_id)
        return user_analyses
    except Exception as e:
        print(f"Error fetching analyses for user {current_user['email']}: {e}")
        raise HTTPException(status_code=500, detail="Could not retrieve your saved analyses.")


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

        formatted_codebase = ""
        for path, content in repo_files.items():
            formatted_codebase += f"--- FILE: {path} ---\n"
            formatted_codebase += f"{content}\n\n"

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
        return {"extensions": sorted(list(unique_extensions)), "repoName": repo_name, "codebase": formatted_codebase}

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"An unexpected error occurred during repository preparation: {e}")
        raise HTTPException(status_code=500, detail="An internal error occurred while preparing repository data.")

@router.delete("/analyses/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_analysis(
    analysis_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Deletes a saved analysis for the authenticated user.
    """
    try:
        user_id = str(current_user["_id"])
        await analysis_service.delete_analysis(analysis_id, user_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except HTTPException as e:
        # Re-raise HTTP exceptions from the service layer
        raise e
    except Exception as e:
        # Catch any other unexpected errors
        print(f"Error deleting analysis {analysis_id}: {e}")
        raise HTTPException(status_code=500, detail="Could not delete the analysis.")