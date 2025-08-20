import socketio
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from ..services import llm_service
from ..core.db import chat_chunks, chat_sessions
from ..core.config import settings

# --- Setup ---
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins="*")
socket_app = socketio.ASGIApp(
    sio,
    socketio_path="/ws/socket.io/"  # Match the client's `path` option
)
embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001", google_api_key=settings.GEMINI_API_KEY)


# --- Event Handlers ---

@sio.event
async def connect(sid, environ, auth):
    """
    Client connects. We get their desired sessionId from the query parameter
    and store it in the Socket.IO session object for this connection.
    """
    # The 'environ' dict contains request details, including the query string.
    query_params = dict(item.split('=') for item in environ.get('QUERY_STRING').split('&'))
    session_id = query_params.get('sessionId')

    print(f"Socket.IO Client Connected: {sid}, attempting to join session: {session_id}")
    if not session_id:
        print(f"Connection from {sid} rejected: No session ID provided in query.")
        return False  # This cleanly rejects the connection

    # Store our application's sessionId in the Socket.IO session for this connection (sid)
    await sio.save_session(sid, {'session_id': session_id})


@sio.event
async def disconnect(sid):
    print(f"Socket.IO Client Disconnected: {sid}")


@sio.event
async def message(sid, data):
    """
    Handles incoming messages. We retrieve our sessionId from the saved session.
    """
    question = data
    session = await sio.get_session(sid)
    session_id = session.get('session_id')

    if not session_id:
        print(f"Cannot process message from {sid}: No session_id found in session.")
        return

    # --- The rest of your RAG logic will now work correctly ---
    try:
        # --- STEP 1: RETRIEVE ALL CONTEXT (Summary, History, and Code) ---
        db_session = await chat_sessions.find_one({"_id": session_id})
        if not db_session or db_session.get("status") != "ready":
            await sio.emit('error', data="Chat session is not ready.", room=sid)
            return

        repository_summary = db_session.get("repositorySummary", "No summary was generated.")
        history = db_session.get("history", [])
        formatted_history = "\n".join([f"{msg['role'].upper()}: {msg['content']}" for msg in history])

        question_embedding = embeddings.embed_query(question)

        # =======================================================================
        # --- ADVANCED RAG - STEP 1: THE "MAP" SEARCH (Summaries Only) ---
        # =======================================================================
        print(f"[{session_id}] Step 1: Searching for relevant file summaries...")
        pipeline_summaries = [
            {"$vectorSearch": {
                "index": "vector_index",
                "path": "embedding",
                "queryVector": question_embedding,
                "numCandidates": 50,
                "limit": 5,
                # CRITICAL: Filter for only summary chunks
                "filter": {"sessionId": session_id, "chunkType": "summary"}
            }},
            {"$project": {"_id": 0, "text": 1, "filePath": 1}}
        ]
        summary_results = await chat_chunks.aggregate(pipeline_summaries).to_list(length=None)

        relevant_file_paths = list(set([doc['filePath'] for doc in summary_results]))
        summary_context = "\n\n".join(
            [f"--- Summary for {doc['filePath']} ---\n{doc['text']}" for doc in summary_results])

        # =======================================================================
        # --- ADVANCED RAG - STEP 2: THE "RETRIEVE" SEARCH (Code Only) ---
        # =======================================================================
        code_context = "No specific code snippets were found for the relevant files."
        if relevant_file_paths:
            print(f"[{session_id}] Step 2: Found {len(relevant_file_paths)} relevant files. Retrieving code chunks...")
            pipeline_code_chunks = [
                {"$vectorSearch": {
                    "index": "vector_index",
                    "path": "embedding",
                    "queryVector": question_embedding,
                    "numCandidates": 150,
                    "limit": 15,
                    # CRITICAL: Filter for code chunks ONLY from the relevant files
                    "filter": {
                        "sessionId": session_id,
                        "chunkType": "code",
                        "filePath": {"$in": relevant_file_paths}
                    }
                }},
                {"$project": {"_id": 0, "text": 1, "filePath": 1}}
            ]
            code_chunk_results = await chat_chunks.aggregate(pipeline_code_chunks).to_list(length=None)
            if code_chunk_results:
                code_context = "\n\n".join(
                    [f"--- From file: {doc.get('filePath', 'Unknown')} ---\n{doc.get('text', '')}" for doc in
                     code_chunk_results])
        else:
            print(f"[{session_id}] Step 2: No relevant file summaries found. Skipping code retrieval.")

        # =======================================================================
        # --- ADVANCED RAG - STEP 3: SYNTHESIZE WITH AN UPGRADED PROMPT ---
        # =======================================================================
        prompt = f"""
            You are an expert-level software architect and code assistant. Your task is to provide a comprehensive answer to the user's question using a multi-layered context.

            You have the following information available:
            1.  **Overall Repository Summary:** A high-level, bird's-eye view of the entire project.
            2.  **Conversation History:** The dialogue so far.
            3.  **Relevant File Summaries:** AI-generated summaries of the files most relevant to the user's question. This is your primary guide.
            4.  **Relevant Code Snippets:** Detailed code chunks from those specific, relevant files.

            --- OVERALL REPOSITORY SUMMARY ---
            {repository_summary}
            --- END OF REPOSITORY SUMMARY ---

            --- CONVERSATION HISTORY ---
            {formatted_history if formatted_history else "This is the first message."}
            --- END OF CONVERSATION HISTORY ---

            --- RELEVANT FILE SUMMARIES ("The Map") ---
            {summary_context if summary_context else "No specific file summaries were found to be relevant."}
            --- END OF RELEVANT FILE SUMMARIES ---

            --- RELEVANT CODE SNIPPETS ("The Details") ---
            {code_context}
            --- END OF CODE SNIPPETS ---

            Based on all the context above, provide a clear, accurate, and detailed answer to the user's latest question: "{question}"
            """

        # --- STEP 4: Generate & Stream Response (No change here) ---
        full_response_text = ""
        response_stream = await llm_service.generate_llm_response(
            prompt=prompt, model_id='gemini-2.5-flash', stream=True
        )
        async for chunk in response_stream:
            full_response_text += chunk
            await sio.emit('message', data=chunk, room=sid)

        # --- STEP 5: Update History in DB (No change here) ---
        new_history_turn = [
            {"role": "user", "content": question},
            {"role": "model", "content": full_response_text}
        ]
        await chat_sessions.update_one(
            {"_id": session_id},
            {"$push": {"history": {"$each": new_history_turn}}}
        )

    except Exception as e:
        print(f"Error in message handler for {sid}: {e}")
        await sio.emit('error', data="Sorry, an error occurred processing your message.", room=sid)