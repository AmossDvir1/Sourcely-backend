from typing import AsyncGenerator
from google import genai
import asyncio

from ..core.config import settings


try:
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
except KeyError:
    raise RuntimeError("GEMINI_API_KEY not found in environment variables.") from None


async def generate_llm_response(
    prompt: str,
    model_id: str,
    stream: bool = False
) -> str | AsyncGenerator[str, None]:
    """
    Interacts with the Google GenAI API. Can be used for both single
    responses and streaming responses for chat.

    Args:
        prompt: The full prompt to send to the LLM.
        model_id: The specific model to use (e.g., 'gemini-pro').
        stream: If True, returns an async generator for streaming.
                If False, returns a single string with the full response.

    Returns:
        Either a complete string or an async generator yielding response chunks.
    """
    try:
        if not stream:
            # --- One-shot generation (for "Analyze") ---
            # This is based on your working code from analysis.py
            response = client.models.generate_content(
                model=model_id, contents=prompt
            )
            return response.text

        else:
            async def stream_generator():
                for chunk in client.models.generate_content_stream(model=model_id, contents=prompt):
                    yield chunk.text
                    await asyncio.sleep(0.01)  # Small delay for smooth streaming

            return stream_generator()

    except Exception as e:
        print(f"An error occurred with the Google GenAI API: {e}")
        # Re-raise the exception so the endpoint can handle it and return a 503 error.
        raise e


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
