
```markdown
# Sourcely Backend: AI-Powered Code Analysis API

---
_This README was generated with ❤️ using the Sourcely application itself!_
---

This document provides a comprehensive overview of the Sourcely Backend, an API designed to analyze and generate insights from source code repositories, particularly those hosted on GitHub.

## 1. General Description

The Sourcely backend serves as the core engine for an AI-powered code analysis platform. Its primary purpose is to provide API endpoints that allow users to submit GitHub repository URLs, retrieve their contents, process them using Large Language Models (LLMs), and generate actionable insights, summaries, and conversational abilities. It is specifically targeted at developers and technical users who wish to gain a deeper understanding of codebases through advanced AI tools.

## 2. Key Technologies

The project is built predominantly with Python and leverages a modern asynchronous stack for high performance:

*   **Language**: Python
*   **Web Framework**: FastAPI (for building robust and high-performance APIs)
*   **Real-time Communication**: Socket.IO (for potential real-time updates and interactive features)
*   **Database**: MongoDB (asynchronous operations managed by Motor)
*   **AI/LLM Integration**: Google Gemini API (via `google-genai` and `langchain_google_genai`)
*   **Authentication**: JWT (JSON Web Tokens, using `python-jose`)
*   **Asynchronous HTTP Client**: `httpx` and `aiohttp`
*   **Data Validation & Settings**: Pydantic
*   **Text Processing**: Langchain (for text splitting and embeddings)
*   **ASGI Server**: Uvicorn

## 3. Core Functionality

The Sourcely backend offers the following key capabilities:

*   **Repository Ingestion**: Fetches repository contents from GitHub.
*   **Advanced Indexing**:
    *   Splits code into manageable "chunks" using `RecursiveCharacterTextSplitter`.
    *   Generates concise, one-paragraph summaries for individual files using an LLM (Gemini 2.5 Flash).
    *   Generates a high-level, comprehensive "instructions file" (repository summary) for the entire codebase using an LLM (Gemini 2.0 Flash Lite), suitable for providing context to other AIs.
    *   Creates vector embeddings for all code and summary chunks using `GoogleGenerativeAIEmbeddings` for efficient semantic search.
*   **Chat Session Management**: Manages chat sessions, storing history and indexed data in MongoDB.
*   **AI-Powered Suggestions**: Automatically generates contextually relevant starter questions for user interaction based on the repository summary.
*   **Analysis Management**: Allows for staging and saving analysis results, associating them with user accounts, and retrieving/deleting previous analyses.

## 4. Setup & Running

To get the Sourcely Backend running locally, follow these steps:

### Prerequisites

*   **Python**: Version 3.8 or higher.
*   **MongoDB**: An active MongoDB instance (local or remote).
*   **Google Gemini API Key**: Obtain a key from the Google AI Studio.
*   **GitHub Personal Access Token (PAT)**: With `public_repo` scope, if you intend to analyze private repositories or hit higher rate limits.

### Installation

1.  **Clone the Repository**:
    ```bash
    git clone <repository_url>
    cd <repository_directory>
    ```

2.  **Create and Activate a Virtual Environment (Recommended)**:
    ```bash
    python -m venv .venv
    # On Linux/macOS:
    source .venv/bin/activate
    # On Windows:
    .venv\Scripts\activate
    ```

3.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

### Environment Variables

Create a `.env` file in the project root directory and populate it with your configuration. Replace placeholder values with your actual keys and settings:

```
MONGO_URI=mongodb://localhost:27017  # Your MongoDB connection string
DB_NAME=sourcely_db
JWT_SECRET=your-strong-jwt-secret-key # **CRITICAL**: Generate a secure, unique key
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
GEMINI_API_KEY=YOUR_GOOGLE_GEMINI_API_KEY
GITHUB_ACCESS_TOKEN=YOUR_GITHUB_PERSONAL_ACCESS_TOKEN
```

### Running the Application

Once everything is set up, start the FastAPI application using Uvicorn:

```bash
uvicorn main:app --host 127.0.0.1 --port 3001 --reload
```
The API will then be accessible at `http://127.0.0.1:3001`.

## 5. Important Configurations

The primary configuration is handled via environment variables loaded into the application's settings, typically managed by `Pydantic` and accessible through `src/core/config.py`. The `.env` file is crucial for defining sensitive credentials and database connection strings.

## 6. Project Structure Overview

The project is organized to separate concerns, with API endpoints, services, and schemas in distinct directories:

```
sourcely-backend/
├── src/
│   ├── api/
│   │   └── v1/
│   │       ├── endpoints/
│   │       │   └── chat.py          # Handles chat session initiation, indexing, AI summaries
│   │       └── __init__.py          # Marks 'v1' as a Python package
│   ├── core/
│   │   ├── config.py                # Application settings and environment variable loading
│   │   └── db.py                    # Database (MongoDB) connection and collection access
│   ├── schemas/
│   │   ├── analysis.py              # Pydantic models for analysis data (input/output)
│   │   └── ...                      # Other data models (e.g., RepoFilesRequest)
│   └── services/
│       ├── analysis_service.py      # Business logic for managing analysis records
│       ├── github_service.py        # Interacts with GitHub API to fetch repo contents
│       ├── llm_service.py           # Handles interactions with LLMs (Google Gemini)
│       └── model_service.py         # (Currently empty, placeholder for future model-related logic)
├── .env.example                     # Template for environment variables
├── main.py                          # Main entry point for the FastAPI application
├── requirements.txt                 # Python dependencies
└── README.md                        # This file
```

## 7. Testing & Coverage

While specific details on testing frameworks and coverage are not explicitly detailed in the provided context, a production-ready application like Sourcely would typically implement:

*   **Unit Tests**: To verify individual functions and components (`src/services/*`, `src/schemas/*`).
*   **Integration Tests**: To ensure different parts of the system (e.g., API endpoints interacting with services and the database) work correctly together.
*   **LLM Mocking**: For testing AI-dependent functionalities without incurring API costs or delays during development.

---
_Thank you for exploring the Sourcely Backend!_
```