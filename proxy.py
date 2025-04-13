"""
Main FastAPI application file for the LLM proxy.
Handles incoming requests, sets up middleware, and routes to the appropriate logic.
"""

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

# Import components from other modules
from config import UPSTREAM_URL # Although not directly used here, good to know it's loaded
from models import ChatCompletionRequest
from streaming import stream_generator

# --- FastAPI App Setup ---
app = FastAPI(
    title="LLM Proxy with Reasoning Split",
    description="A proxy for LLM APIs that splits reasoning (<think>) tags into a separate field.",
    version="1.0.0"
)

# --- Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Restrict this in production environments
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- API Endpoints ---

@app.post("/v1/chat/completions",
          summary="Proxies chat completion requests to an upstream LLM API",
          description="Accepts OpenAI-compatible chat completion requests, forwards them to the "
                      "configured upstream URL, and streams the response back. It processes the "
                      "stream to separate content enclosed in <think>...</think> tags into a "
                      "'reasoning' field in the SSE chunks.",
          response_description="A Server-Sent Events (SSE) stream. Each event contains a JSON payload "
                               "compatible with OpenAI's streaming format, potentially with an added "
                               "'reasoning' field in the 'delta' object for thinking steps.",
          tags=["LLM Proxy"])
async def chat_completion(
    request_body: ChatCompletionRequest, # Renamed for clarity
    raw_request: Request # Keep access to raw request for headers
):
    """Handles the chat completion request, prepares headers, and initiates streaming."""
    print(f"Received request for model: {request_body.model}") # Basic logging

    # Prepare headers for the upstream request
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        # Add Authorization header if present in the incoming request
        "Authorization": raw_request.headers.get("Authorization", ""),
        # Add any other headers required by your upstream API if necessary
        # "X-Api-Key": "YOUR_UPSTREAM_API_KEY", # Example
    }
    # Filter out empty Authorization header if it wasn't present
    if not headers["Authorization"]:
        del headers["Authorization"]

    # The actual streaming logic is handled by stream_generator
    # Pass the validated request body and constructed headers
    return StreamingResponse(
        stream_generator(request_body, headers),
        media_type="text/event-stream"
    )

@app.get("/",
         summary="Root endpoint for health check",
         description="A simple endpoint to confirm the proxy server is running.",
         tags=["Health Check"])
def read_root():
    """Returns a simple message indicating the server is running."""
    return {"message": "LLM Proxy with Reasoning Split is running"}

# --- Run Instructions (for development) ---
# Use: uvicorn proxy:app --reload --host 0.0.0.0 --port 8000
