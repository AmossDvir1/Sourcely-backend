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

async def _generate_repository_summary(full_code_context: str) -> str:
    """
    Performs a one-time analysis of the entire repository to create
    the summary "instructions file".
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
    The full background process that runs when a chat is prepared.
    This version correctly preserves file path metadata for each chunk.
    """
    try:
        print(f"[{session_id}] Starting indexing for {github_url}")
        repo_files = await github_service.get_repo_contents_from_url(github_url)

        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=200)

        # --- REFACTORED CHUNKING LOGIC ---
        all_chunks = []
        # 1. Iterate through each file in the repository
        for path, content in repo_files.items():
            # 2. Split the content of THIS file into chunks
            file_chunks = text_splitter.split_text(content)

            # 3. Create a list of objects, associating each chunk with its file path
            for chunk in file_chunks:
                all_chunks.append({
                    "text": chunk,
                    "filePath": path  # <-- PRESERVE THE METADATA
                })

        if all_chunks:
            print(f"[{session_id}] Created {len(all_chunks)} text chunks. Generating embeddings...")

            # 4. Extract just the text for the embedding model
            chunk_texts = [chunk['text'] for chunk in all_chunks]
            chunk_embeddings = embeddings.embed_documents(chunk_texts)

            # 5. Build the final documents for insertion, now with all the data
            documents_to_insert = [
                {
                    "sessionId": session_id,
                    "text": all_chunks[i]["text"],
                    "filePath": all_chunks[i]["filePath"],  # <-- INCLUDE THE METADATA
                    "embedding": chunk_embeddings[i]
                }
                for i in range(len(all_chunks))
            ]
            await chat_chunks.insert_many(documents_to_insert)

        # --- Summary generation remains the same ---
        full_code_context = "\n\n".join([f"--- FILE: {path} ---\n{content}" for path, content in repo_files.items()])
        repository_summary = await _generate_repository_summary(full_code_context)

        await chat_sessions.update_one(
            {"_id": session_id},
            {"$set": {"repositorySummary": repository_summary, "status": "ready"}}
        )
        print(f"[{session_id}] Indexing and summary generation complete. Status -> ready.")

    except Exception as e:
        print(f"[{session_id}] Error during indexing: {e}. Status -> error.")
        await chat_sessions.update_one({"_id": session_id}, {"$set": {"status": "error"}})

# --- API Endpoints ---

@router.post("/chat/prepare")
async def prepare_chat(data: RepoFilesRequest):
    """
    Creates a new chat session, saves it to the DB, and starts the background indexing task.
    """
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
    """
    Allows the frontend to poll for the status of the indexing job.
    """
    session = await chat_sessions.find_one({"_id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found.")
    return {"status": session.get("status")}