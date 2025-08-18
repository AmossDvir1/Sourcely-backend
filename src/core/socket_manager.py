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
        pipeline = [
            {
                "$vectorSearch": {
                    "index": "vector_index",
                    "path": "embedding",
                    "queryVector": question_embedding,
                    "numCandidates": 100,
                    "limit": 15,
                    "filter": {"sessionId": session_id}
                }
            },
            {
                # FIX: Use a pure inclusion projection.
                # By only asking for 'text' and 'filePath', we implicitly
                # exclude the large 'embedding' vector.
                "$project": {
                    "_id": 0,  # It's always okay to exclude _id.
                    "text": 1,  # Include the text content.
                    "filePath": 1  # Include the file path metadata.
                }
            }
        ]
        results = await chat_chunks.aggregate(pipeline).to_list(length=None)
        code_context = "\n\n".join([f"--- From file: {doc.get('filePath', 'Unknown File')} ---\n{doc.get('text', '')}" for doc in results])


        # --- STEP 2: BUILD THE ENHANCED, MULTI-CONTEXT PROMPT ---
        prompt = f"""
        You are an expert code assistant. Address and answer the user's question accurately and consistently, using the provided context.

        You have three sources of information:
        1. **Repository Summary:** A high-level overview.
        2. **Conversation History:** The dialogue so far.
        3. **Relevant Code Snippets:** Specific code related to the latest question.

        --- REPOSITORY SUMMARY ---
        {repository_summary}
        --- END OF REPOSITORY SUMMARY ---
        --- CONVERSATION HISTORY ---
        {formatted_history if formatted_history else "This is the first message."}
        --- END OF CONVERSATION HISTORY ---
        --- RELEVANT CODE SNIPPETS ---
        {code_context if code_context else "No specific code snippets were found."}
        --- END OF CODE SNIPPETS ---

        Answer the user's latest question: {question}
        Answer it (or do what the user asks).
        """
        print("--------------", code_context, repository_summary, formatted_history, sep="----------------------")

        # --- STEP 3: GENERATE & STREAM RESPONSE ---
        full_response_text = ""
        response_stream = await llm_service.generate_llm_response(
            prompt=prompt, model_id='gemini-2.5-flash', stream=True
        )
        async for chunk in response_stream:
            full_response_text += chunk
            await sio.emit('message', data=chunk, room=sid)

        # --- STEP 4: UPDATE HISTORY IN DB ---
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
