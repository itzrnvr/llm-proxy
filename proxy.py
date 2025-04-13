"""
Main FastAPI application file for the LLM proxy.
Handles incoming requests, sets up middleware, and routes to the appropriate logic.
"""

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

# Import components from other modules
# from config import UPSTREAM_URL # No longer needed for routing
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

@app.post("/proxy/{provider_base_url:path}/v1/chat/completions",
          summary="Dynamically proxies chat completion requests to any upstream LLM API",
          description="Accepts OpenAI-compatible chat completion requests. Extracts the target provider's "
                      "base URL from the path, forwards the request (with headers and body) to the "
                      "constructed target URL (provider_base_url + '/v1/chat/completions'), and streams "
                      "the response back. It universally processes the stream to separate content "
                      "enclosed in <think>...</think> tags into a 'reasoning' field in the SSE chunks.",
          response_description="A Server-Sent Events (SSE) stream. Each event contains a JSON payload "
                               "compatible with OpenAI's streaming format, with an added 'reasoning' "
                               "field in the 'delta' object for thinking steps.",
          tags=["LLM Proxy"])
async def chat_completion(
    provider_base_url: str, # Captured from path
    request_body: ChatCompletionRequest,
    raw_request: Request # Keep access to raw request for headers
):
    """Handles the dynamic chat completion request, constructs target URL, prepares headers, and initiates streaming."""
    # Construct the full target URL
    # Ensure no double slashes if provider_base_url ends with /
    provider_base_url = provider_base_url.rstrip('/')
    target_url = f"{provider_base_url}/v1/chat/completions"
    print(f"Proxying request for model '{request_body.model}' to: {target_url}")

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
        stream_generator(target_url, request_body, headers),
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
