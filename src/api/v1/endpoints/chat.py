from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings
import asyncio
import uuid
import os
from datetime import datetime, timezone

from ....schemas.analysis import RepoFilesRequest
from ....services import github_service, llm_service
from ....core.config import settings
from ....core.db import chat_chunks, chat_sessions

router = APIRouter()

embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001", google_api_key=settings.GEMINI_API_KEY)


# --- Helper function for generating the "instructions file" ---
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


# --- Main background task for indexing and summarizing ---
async def index_repository(github_url: str, session_id: str):
    """
    The full background process:
    1. Fetches code from GitHub.
    2. Chunks and embeds the code, saving to 'chat_chunks' collection.
    3. Generates a high-level summary of the entire repository.
    4. Updates the 'chat_sessions' document with the summary and sets status to "ready".
    """
    try:
        # 1. Fetch all repo files
        print(f"[{session_id}] Starting indexing for {github_url}")
        repo_files = await github_service.get_repo_contents_from_url(github_url)

        # 2. Chunk, embed, and store vector data
        all_text_docs = [f"--- FILE: {path} ---\n{content}" for path, content in repo_files.items()]
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=200)
        chunks = text_splitter.split_text("\n\n".join(all_text_docs))

        if chunks:
            print(f"[{session_id}] Created {len(chunks)} text chunks. Generating embeddings...")
            chunk_embeddings = embeddings.embed_documents(chunks)
            documents_to_insert = [
                {"sessionId": session_id, "text": text, "embedding": chunk_embeddings[i]}
                for i, text in enumerate(chunks)
            ]
            await chat_chunks.insert_many(documents_to_insert)

        # 3. Generate the high-level summary
        full_code_context = "\n\n".join([f"--- FILE: {path} ---\n{content}" for path, content in repo_files.items()])
        repository_summary = await _generate_repository_summary(full_code_context)

        # 4. Update the session document with the summary and set status to "ready"
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


@router.websocket("/ws/chat/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """
    Handles the live chat connection, retrieves context (including history),
    and streams LLM responses while maintaining conversation memory.
    """
    session = await chat_sessions.find_one({"_id": session_id})
    if not session or session.get("status") != "ready":
        await websocket.close(code=1011, reason="Chat session not ready or invalid.")
        return

    await websocket.accept()

    # Fetch the static context once at the start of the connection
    repository_summary = session.get("repositorySummary", "No summary was generated for this repository.")

    try:
        while True:
            question = await websocket.receive_text()

            # --- STEP 1: RETRIEVE ALL CONTEXT (History, Summary, and Code) ---

            # 1a. Get the current conversation history from the database
            current_session = await chat_sessions.find_one({"_id": session_id})
            history = current_session.get("history", [])

            # Format the history for the prompt
            formatted_history = "\n".join([f"{msg['role'].upper()}: {msg['content']}" for msg in history])

            # 1b. Retrieve specific code context via vector search
            question_embedding = embeddings.embed_query(question)
            pipeline = [
                {"$vectorSearch": {
                    "index": "vector_index", "path": "embedding",
                    "queryVector": question_embedding, "numCandidates": 100, "limit": 15,
                    "filter": {"sessionId": session_id}
                }}
            ]
            results = await chat_chunks.aggregate(pipeline).to_list(length=None)
            code_context = "\n\n".join([doc['text'] for doc in results])

            # 2. Build the enhanced prompt with both summary and code context
            prompt = f"""
            You are an expert code assistant. Your goal is to answer the user's question accurately and consistently, maintaining the context of the ongoing conversation.
            Do no mention the fact that you have the high-level Repository Summary or code snippets as context.

            You have three sources of information:
            1. **Repository Summary:** A high-level overview of the project.
            2. **Conversation History:** The dialogue you have had with the user so far.
            3. **Relevant Code Snippets:** Specific code chunks related to the user's most recent question.

            Use all three sources to formulate your answer. Be consistent with your previous responses in the conversation history.

            --- REPOSITORY SUMMARY ---
            {repository_summary}
            --- END OF REPOSITORY SUMMARY ---

            --- CONVERSATION HISTORY ---
            {formatted_history if formatted_history else "This is the first message in the conversation."}
            --- END OF CONVERSATION HISTORY ---

            --- RELEVANT CODE SNIPPETS ---
            {code_context if code_context else "No specific code snippets were found for this question."}
            --- END OF CODE SNIPPETS ---

            Based on all of the above information, answer the user's latest question: {question}
            """

            full_response_text = ""

            # 3. Generate and stream the response using the LLM service
            try:
                response_stream = await llm_service.generate_llm_response(
                    prompt=prompt, model_id='gemini-2.0-flash-lite', stream=True
                )
                async for chunk in response_stream:
                    full_response_text += chunk  # Accumulate the full response for saving
                    await websocket.send_text(chunk)

                # --- STEP 4: UPDATE THE DATABASE WITH THE NEW TURN ---
                new_history_turn = [
                    {"role": "user", "content": question},
                    {"role": "model", "content": full_response_text}
                ]

                # Atomically add the user's question and the model's full answer to the history array
                await chat_sessions.update_one(
                    {"_id": session_id},
                    {"$push": {"history": {"$each": new_history_turn}}}
                )
            except Exception as e:
                print(f"[{session_id}] LLM generation failed: {e}")
                await websocket.send_text("Sorry, an error occurred while generating the response.")

    except WebSocketDisconnect:
        print(f"[{session_id}] Client disconnected.")
    except Exception as e:
        print(f"[{session_id}] An error occurred in the websocket: {e}")
