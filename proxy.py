from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import re
import json
import copy # Needed for deep copying chunk structure
from typing import Optional, List, Dict, Any # Use List/Dict/Any for older Python versions if needed

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Configuration ---
UPSTREAM_URL = "https://llm.chutes.ai/v1/chat/completions" # Your upstream API
# --- ------------- ---

class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[Dict[str, Any]] # Use List/Dict/Any for broader compatibility
    stream: Optional[bool] = True
    # Add any other passthrough parameters your frontend might send
    # temperature: Optional[float] = None
    # max_tokens: Optional[int] = None
    # ... other OpenAI compatible params

# Route: Modified OpenAI-compatible /chat/completions
@app.post("/v1/chat/completions")
async def chat_completion(request: ChatCompletionRequest, raw_request: Request):
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    auth_header = raw_request.headers.get("Authorization")
    if auth_header:
        headers["Authorization"] = auth_header
    # Add other necessary headers if needed

    # Ensure stream=True is always sent upstream
    # Pass through any extra compatible parameters from the request body
    openai_payload = request.model_dump(exclude_unset=True) # Use Pydantic's method
    openai_payload["stream"] = True # Force streaming

    # 3. Define the Async Generator for Streaming Response
    async def stream_generator():
        is_thinking = False # State variable: True if inside <think>...</think>
        buffer = "" # Buffer for potentially incomplete tags across chunks

        try:
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST",
                    UPSTREAM_URL,
                    json=openai_payload,
                    headers=headers,
                    timeout=180.0 # Longer timeout for potentially slow streams/thinking
                ) as response:
                    if response.status_code >= 400:
                         error_body = await response.aread()
                         # Try to parse JSON error, fallback to raw text
                         try:
                             detail = json.loads(error_body.decode())
                         except json.JSONDecodeError:
                             detail = f"Upstream API error (non-JSON): {error_body.decode()}"
                         print(f"Upstream error: {response.status_code} - {detail}")
                         # Send an error chunk (non-standard but informative)
                         error_chunk = {
                             "error": {
                                 "message": f"Upstream API error: Status {response.status_code}",
                                 "type": "upstream_error",
                                 "param": None,
                                 "code": str(response.status_code),
                                 "detail": detail # Include upstream detail if possible
                             }
                         }
                         yield f"data: {json.dumps(error_chunk)}\n\n"
                         yield f"data: [DONE]\n\n" # Signal end even on error
                         return # Stop generation

                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue

                        if line.startswith("data:"):
                            data_content = line[len("data:"):].strip()

                            if data_content == "[DONE]":
                                # Process any remaining buffer before finishing
                                if buffer:
                                     # This buffer content must be the last part
                                     # Decide if it's reasoning or content based on final state
                                     field_name = "reasoning" if is_thinking else "content"
                                     # Need a dummy chunk structure to yield this last bit
                                     # This is tricky, ideally the last chunk before DONE has the content
                                     # Let's assume the last *real* chunk handled its content
                                     print(f"Warning: Leftover buffer at [DONE]: '{buffer}' (State: {'thinking' if is_thinking else 'content'}) - Discarding.")
                                     buffer = "" # Clear buffer

                                yield f"data: [DONE]\n\n"
                                print("Stream finished.")
                                break # Exit the loop cleanly

                            try:
                                chunk_json = json.loads(data_content)
                                # --- State Machine Logic ---
                                current_content = ""
                                delta = {}
                                if (choices := chunk_json.get("choices")) and len(choices) > 0:
                                     delta = choices[0].get("delta", {})
                                     current_content = delta.get("content", "") or "" # Ensure it's a string

                                # Always pass through non-content delta updates (like role) or finish_reason
                                if not current_content and (delta.get("role") or choices[0].get("finish_reason") is not None):
                                     # If there's leftover buffer content before this final chunk, process it
                                     if buffer:
                                          yield_field = "reasoning" if is_thinking else "content"
                                          # Create a minimal chunk for the buffer content
                                          buffer_chunk = copy.deepcopy(chunk_json) # Base structure
                                          buffer_chunk["choices"][0]["delta"] = {yield_field: buffer}
                                          if "finish_reason" in buffer_chunk["choices"][0]:
                                              del buffer_chunk["choices"][0]["finish_reason"] # Remove finish reason from this buffer chunk
                                          if "content" in buffer_chunk["choices"][0]["delta"] and yield_field == "reasoning":
                                              buffer_chunk["choices"][0]["delta"]["content"] = None
                                          if "reasoning" in buffer_chunk["choices"][0]["delta"] and yield_field == "content":
                                               buffer_chunk["choices"][0]["delta"]["reasoning"] = None

                                          yield f"data: {json.dumps(buffer_chunk)}\n\n"
                                          print(f"Yielded final buffer part ({yield_field}): '{buffer}'")
                                          buffer = "" # Clear buffer

                                     # Now yield the original chunk (role or finish_reason)
                                     # Ensure it doesn't contain leftover content/reasoning fields if we just yielded buffer
                                     final_chunk = copy.deepcopy(chunk_json)
                                     if "content" in final_chunk["choices"][0].get("delta",{}):
                                         final_chunk["choices"][0]["delta"]["content"] = None
                                     if "reasoning" in final_chunk["choices"][0].get("delta",{}):
                                         final_chunk["choices"][0]["delta"]["reasoning"] = None

                                     yield f"data: {json.dumps(final_chunk)}\n\n"
                                     print(f"Yielded non-content chunk: {final_chunk}")
                                     continue # Move to next line

                                # Process content if present
                                if current_content:
                                    buffer += current_content # Add new content to buffer

                                    while True: # Process buffer until no more tags found
                                        if is_thinking:
                                            # Currently thinking, look for end tag
                                            end_tag_match = re.search(r"</think>", buffer, re.IGNORECASE | re.DOTALL)
                                            if end_tag_match:
                                                # Found end tag
                                                reasoning_part = buffer[:end_tag_match.start()]
                                                if reasoning_part:
                                                    # Yield reasoning part
                                                    output_chunk = copy.deepcopy(chunk_json) # Copy base structure
                                                    output_chunk["choices"][0]["delta"] = {"reasoning": reasoning_part}
                                                    # Remove finish_reason if it exists in this intermediate chunk
                                                    if "finish_reason" in output_chunk["choices"][0]: del output_chunk["choices"][0]["finish_reason"]
                                                    yield f"data: {json.dumps(output_chunk)}\n\n"
                                                    print(f"Yielded reasoning: '{reasoning_part}'")

                                                buffer = buffer[end_tag_match.end():] # Update buffer (remove tag)
                                                is_thinking = False # State change
                                                # Continue processing the rest of the buffer in the next loop iteration
                                            else:
                                                # No end tag found in buffer yet, yield entire buffer as reasoning
                                                if buffer:
                                                    output_chunk = copy.deepcopy(chunk_json)
                                                    output_chunk["choices"][0]["delta"] = {"reasoning": buffer}
                                                    if "finish_reason" in output_chunk["choices"][0]: del output_chunk["choices"][0]["finish_reason"]
                                                    yield f"data: {json.dumps(output_chunk)}\n\n"
                                                    print(f"Yielded partial reasoning: '{buffer}'")
                                                buffer = "" # Clear buffer as it was yielded
                                                break # Wait for more chunks
                                        else:
                                            # Not thinking, look for start tag
                                            start_tag_match = re.search(r"<think>", buffer, re.IGNORECASE | re.DOTALL)
                                            if start_tag_match:
                                                # Found start tag
                                                content_part = buffer[:start_tag_match.start()]
                                                if content_part:
                                                    # Yield content part
                                                    output_chunk = copy.deepcopy(chunk_json)
                                                    output_chunk["choices"][0]["delta"] = {"content": content_part}
                                                    if "finish_reason" in output_chunk["choices"][0]: del output_chunk["choices"][0]["finish_reason"]
                                                    yield f"data: {json.dumps(output_chunk)}\n\n"
                                                    print(f"Yielded content: '{content_part}'")

                                                buffer = buffer[start_tag_match.end():] # Update buffer (remove tag)
                                                is_thinking = True # State change
                                                # Continue processing the rest of the buffer
                                            else:
                                                # No start tag found, yield entire buffer as content
                                                if buffer:
                                                    output_chunk = copy.deepcopy(chunk_json)
                                                    output_chunk["choices"][0]["delta"] = {"content": buffer}
                                                    if "finish_reason" in output_chunk["choices"][0]: del output_chunk["choices"][0]["finish_reason"]
                                                    yield f"data: {json.dumps(output_chunk)}\n\n"
                                                    print(f"Yielded partial content: '{buffer}'")
                                                buffer = "" # Clear buffer
                                                break # Wait for more chunks


                            except json.JSONDecodeError:
                                print(f"Warning: Could not decode JSON from upstream chunk: {data_content}")
                                continue
                            except Exception as e:
                                print(f"Error processing chunk: {e}")
                                # Optional: yield an error chunk (non-standard)
                                # yield f"data: {json.dumps({'error': {'message': f'Proxy error processing chunk: {e}', 'type': 'proxy_error'}})}\n\n"
                                # Consider breaking or continuing based on severity
                                break # Break on processing errors for safety

                        else:
                            print(f"Warning: Received unexpected line format from upstream: {line}")


        except httpx.RequestError as e:
            print(f"Error connecting to upstream API: {e}")
            # Yield a non-standard error chunk
            yield f"data: {json.dumps({'error': {'message': f'Upstream connection error: {e}', 'type': 'proxy_error'}})}\n\n"
            yield f"data: [DONE]\n\n" # Ensure termination signal

        except HTTPException as e:
            # This likely happens if the initial connection failed before streaming started
             print(f"HTTP Exception before streaming started: {e.detail}")
             # Cannot yield here as response hasn't started. FastAPI handles this.
             raise e # Re-raise to let FastAPI handle it

        except Exception as e:
            print(f"Unexpected error during streaming: {e}")
            import traceback
            traceback.print_exc() # Print full traceback for debugging
            # Yield a non-standard error chunk
            yield f"data: {json.dumps({'error': {'message': f'Internal proxy error during stream: {e}', 'type': 'proxy_error'}})}\n\n"
            yield f"data: [DONE]\n\n" # Ensure termination signal

        finally:
             # Final check for any remaining buffer content if stream ended abruptly
             if buffer:
                 final_field = "reasoning" if is_thinking else "content"
                 # Create a minimal final chunk
                 # We lack the original chunk context here, so create a basic one
                 final_buffer_chunk = {
                     "id": "proxy_final_buffer", # Indicate proxy generated
                     "object": "chat.completion.chunk",
                     "created": 0, # Placeholder
                     "model": request.model, # Use requested model
                     "choices": [{
                         "index": 0,
                         "delta": {final_field: buffer},
                         "finish_reason": None
                     }]
                 }
                 yield f"data: {json.dumps(final_buffer_chunk)}\n\n"
                 print(f"Yielded final buffer content from finally block ({final_field}): '{buffer}'")

             print("Stream generator finished.")


    # 4. Create and Return Streaming Response
    return StreamingResponse(stream_generator(), media_type="text/event-stream")

# Optional: Add a root endpoint for testing
@app.get("/")
def read_root():
    return {"message": "LLM Proxy with Reasoning Split is running"}

# Run command: uvicorn proxy2:app --reload --host 0.0.0.0 --port 8000
