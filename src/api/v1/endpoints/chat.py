import json
from fastapi import APIRouter, HTTPException
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings
import asyncio
import uuid
from datetime import datetime, timezone

from ....schemas.analysis import RepoFilesRequest
from ....services import github_service, llm_service
from ....core.config import settings
from ....core.db import chat_chunks, chat_sessions

router = APIRouter()

embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001", google_api_key=settings.GEMINI_API_KEY)


# --- Helper functions for the background indexing task ---

async def _generate_file_summary(file_path: str, file_content: str) -> str:
    """
    Generates a concise, one-paragraph summary for a single source code file.
    """
    prompt = f"""
    You are an expert code analyst. Your task is to generate a concise, high-level summary 
    for the following source code file. Focus on the file's primary purpose, its main functions
    or classes, and how it might interact with other parts of the application.

    **CRITICAL:** The summary must be a single paragraph.

    --- FILE PATH ---
    {file_path}

    --- FILE CONTENT ---
    {file_content}
    --- END OF CONTENT ---

    Generate the one-paragraph summary now.
    """
    try:
        summary = await llm_service.generate_llm_response(
            prompt=prompt, model_id='gemini-2.5-flash', stream=False
        )

        # --- THIS IS THE FIX ---
        # Add a defensive check to ensure we never return None.
        # If the LLM response is blocked or empty, provide a fallback string.
        if summary is None:
            print(f"Warning: LLM returned None for summary of {file_path}. Using fallback.")
            return f"// A summary could not be generated for the file {file_path}."

        return summary

    except Exception as e:
        print(f"Could not generate summary for {file_path}: {e}")
        return f"// Summary generation failed for {file_path} due to an error."


async def _generate_ai_suggestions(repository_summary: str) -> list[str]:
    """
    (This function is unchanged)
    """
    print("Generating AI-powered chat suggestions...")
    prompt = f"""
    You are a helpful AI assistant tasked with creating smart chat suggestions for a developer UI.
    Your goal is to generate exactly 4 starter questions based on the provided repository summary.
    **CRITICAL CONSTRAINTS:**
    1.  **Question Mix:** 2 "Domain-Specific" Questions and 2 "Contextual Engineering" Questions.
    2.  **Length Limit:** Each question MUST BE 60 CHARACTERS OR LESS.
    3.  **Avoid Trivial Questions:** Do NOT ask "What is this project?".
    --- REPOSITORY SUMMARY ---
    {repository_summary}
    --- END OF SUMMARY ---
    Return ONLY a JSON array of 4 strings.
    """
    try:
        response_text = await llm_service.generate_llm_response(
            prompt=prompt, model_id='gemini-2.0-flash-lite', stream=False
        )
        cleaned_response = response_text.strip().replace("```json", "").replace("```", "").strip()
        suggestions = json.loads(cleaned_response)
        if isinstance(suggestions, list) and all(isinstance(s, str) for s in suggestions):
            print(f"Successfully generated specific suggestions: {suggestions}")
            return suggestions
        else:
            raise ValueError("Parsed JSON is not a list of strings.")
    except Exception as e:
        print(f"Failed to generate or parse specific AI suggestions: {e}. Falling back to defaults.")
        return [
            "What is the general purpose of this project?",
            "How do I set up the development environment?",
            "What are the key technologies used?",
            "Can you explain the project's file structure?",
        ]


async def _generate_repository_summary(full_code_context: str) -> str:
    """
    (This function is unchanged)
    """
    print("Generating high-level repository summary...")
    prompt = f"""
    You are an expert software architect. Analyze the entire provided codebase and generate a concise, well-structured "instructions file" in Markdown format. This file will serve as high-level context for another AI. Include:
    1. **General Description:** Project purpose and target audience.
    2. **Key Technologies:** Main frameworks, languages, and important libraries.
    3. **Setup & Running:** Step-by-step instructions to run the project.
    4. **Testing & Coverage:** Brief description of how the tests work, which technology is used, approximate amount of coverage in this project.
    5. **Core Functionality:** Brief description of key features/modules.
    6. **File Tree Structure:** ASCII Schema of the Tree File Structure.
    7. **Important Configs:** Point out critical configuration files.
    --- FULL REPOSITORY CODE ---
    {full_code_context}
    --- END OF CODE ---
    Generate the instructions file now.
    """
    try:
        summary = await llm_service.generate_llm_response(
            prompt=prompt, model_id='gemini-2.0-flash-lite', stream=False
        )
        print("Repository summary generated successfully.")
        return summary
    except Exception as e:
        print(f"Failed to generate repository summary: {e}")
        return "Error: Could not generate a summary for this repository."


async def index_repository(github_url: str, session_id: str):
    """
    (This function is unchanged)
    """
    try:
        print(f"[{session_id}] Starting advanced indexing for {github_url}")
        repo_files = await github_service.get_repo_contents_from_url(github_url)
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=200)

        all_chunks_to_embed = []

        # --- PART 1: Create 'code' chunks from the raw source code ---
        print(f"[{session_id}] Creating 'code' chunks...")
        for path, content in repo_files.items():
            file_chunks = text_splitter.split_text(content)
            for chunk in file_chunks:
                all_chunks_to_embed.append({
                    "text": chunk,
                    "filePath": path,
                    "chunkType": "code"
                })

        # --- PART 2: Create 'summary' chunks for each file ---
        print(f"[{session_id}] Creating 'summary' chunks for {len(repo_files)} files...")
        summary_tasks = [
            _generate_file_summary(path, content) for path, content in repo_files.items()
        ]
        file_summaries = await asyncio.gather(*summary_tasks)

        for i, (path, _) in enumerate(repo_files.items()):
            all_chunks_to_embed.append({
                "text": file_summaries[i],
                "filePath": path,
                "chunkType": "summary"
            })

        if all_chunks_to_embed:
            print(f"[{session_id}] Created {len(all_chunks_to_embed)} total chunks. Generating embeddings...")

            chunk_texts = [chunk['text'] for chunk in all_chunks_to_embed]
            chunk_embeddings = embeddings.embed_documents(chunk_texts)

            documents_to_insert = [
                {
                    "sessionId": session_id,
                    "text": all_chunks_to_embed[i]["text"],
                    "filePath": all_chunks_to_embed[i]["filePath"],
                    "chunkType": all_chunks_to_embed[i]["chunkType"],
                    "embedding": chunk_embeddings[i]
                }
                for i in range(len(all_chunks_to_embed))
            ]
            await chat_chunks.insert_many(documents_to_insert)

        # --- PART 3: Overall Summary and Suggestions ---
        full_code_context = "\n\n".join([f"--- FILE: {path} ---\n{content}" for path, content in repo_files.items()])
        repository_summary = await _generate_repository_summary(full_code_context)
        ai_suggestions = await _generate_ai_suggestions(repository_summary)

        await chat_sessions.update_one(
            {"_id": session_id},
            {"$set": {"repositorySummary": repository_summary, "status": "ready", "aiSuggestions": ai_suggestions}}
        )
        print(f"[{session_id}] Advanced indexing complete. Status -> ready.")

    except Exception as e:
        print(f"[{session_id}] Error during advanced indexing: {e}. Status -> error.")
        await chat_sessions.update_one({"_id": session_id}, {"$set": {"status": "error"}})


# --- API Endpoints (Unchanged) ---

@router.post("/chat/prepare")
async def prepare_chat(data: RepoFilesRequest):
    session_id = str(uuid.uuid4())
    await chat_sessions.insert_one({
        "_id": session_id,
        "status": "preparing",
        "createdAt": datetime.now(timezone.utc),
        "history": []
    })
    asyncio.create_task(index_repository(data.githubUrl, session_id))
    return {"chatSessionId": session_id}


@router.get("/chat/status/{session_id}")
async def get_chat_status(session_id: str):
    session = await chat_sessions.find_one({"_id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found.")

    status = session.get("status")
    response = {"status": status}

    if status == "ready":
        response["suggestions"] = session.get("aiSuggestions", [])

    return response