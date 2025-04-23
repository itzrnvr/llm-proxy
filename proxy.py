import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
import os
import asyncio

app = FastAPI()

# Configuration - simplified example
UPSTREAM_URL = "https://api.openai.com/v1/chat/completions" # Or another compatible API
API_KEY = os.environ.get("UPSTREAM_API_KEY") # Get the key for the actual provider

# Use a persistent client for connection pooling
client = httpx.AsyncClient()

@app.post("/v1/chat/completions")
async def proxy_chat_completions(request: Request):
    # 1. Get raw body and headers from the incoming request
    raw_body = await request.body()
    headers = dict(request.headers)

    # 2. Prepare headers for the upstream request
    upstream_headers = {
        "Content-Type": headers.get("content-type", "application/json"),
        "Authorization": f"Bearer {API_KEY}", # Use the proxy's key
        # Pass through other relevant headers if needed (e.g., custom user-agent)
    }

    # 3. Check if streaming is requested
    #    (Need to parse the JSON body carefully, might need error handling)
    is_streaming = False
    try:
        # Avoid parsing the whole body if large, maybe peek or use a streaming parser
        # This simple json.loads is okay for typical sizes but not ideal for huge bodies
        import json
        payload = json.loads(raw_body)
        is_streaming = payload.get("stream", False)
    except json.JSONDecodeError:
        # Handle cases where body isn't valid JSON
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # 4. Define the async generator for streaming
    async def stream_generator():
        try:
            async with client.stream(
                "POST",
                UPSTREAM_URL,
                content=raw_body,
                headers=upstream_headers,
                timeout=300.0 # Set a reasonable timeout
            ) as response:
                # Raise exceptions for bad upstream responses (like 4xx, 5xx)
                # response.raise_for_status() # Careful: this reads the body for non-2xx, might break streaming logic
                if response.status_code >= 400:
                     # Read error details if possible without breaking stream
                     error_body = await response.aread()
                     print(f"Upstream Error {response.status_code}: {error_body.decode()}")
                     # Yielding an error message back in SSE format might be desired
                     # For now, just stop iteration
                     # yield f"data: {{\"error\": \"Upstream error {response.status_code}\"}}\n\n"
                     return # Stop the generator

                async for chunk in response.aiter_bytes():
                    yield chunk
                    await asyncio.sleep(0) # Allow context switching if needed

        except httpx.RequestError as e:
            # Handle network errors connecting to upstream
            print(f"Upstream request error: {e}")
            # Optionally yield an error message back to the client in SSE format
            # yield f"data: {{\"error\": \"Proxy failed to connect to upstream\"}}\n\n"
        except Exception as e:
            # General error handling
             print(f"An unexpected error occurred during streaming: {e}")
            # yield f"data: {{\"error\": \"An unexpected error occurred\"}}\n\n"


    # 5. Make the request and handle response based on streaming
    if is_streaming:
        # Return a StreamingResponse using the generator
        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream" # Crucial for SSE
            # Pass through status code/headers from upstream if needed
        )
    else:
        # Make a non-streaming request
        try:
            response = await client.post(
                UPSTREAM_URL,
                content=raw_body,
                headers=upstream_headers,
                timeout=300.0
            )
            # Check status code before returning
            if response.status_code >= 400:
                 raise HTTPException(status_code=response.status_code, detail=await response.atext())

            # Return the full response body and relevant headers
            # Note: Returning raw bytes and letting FastAPI handle JSON is often best
            return response.content # Or response.json() if sure it's JSON
            # Consider forwarding specific headers from upstream response too

        except httpx.RequestError as e:
             raise HTTPException(status_code=502, detail=f"Upstream request error: {e}") # Bad Gateway


# Remember to add other endpoints like /v1/embeddings in a similar fashion

# To run (install uvicorn and fastapi):
# uvicorn your_module_name:app --reload