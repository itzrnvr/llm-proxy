"""Handles the core logic for streaming and processing LLM responses."""

import httpx
import re
import json
import copy
from typing import List, Dict, Any, AsyncGenerator

from fastapi import HTTPException # Keep for potential re-raise? Or handle differently? Let's keep for now.

from config import UPSTREAM_URL
from models import ChatCompletionRequest


async def process_chunk_buffer(buffer: str, is_thinking: bool, chunk_json: dict) -> tuple[str, dict | None, bool]:
    """Process the buffer content based on <think> tags.

    Args:
        buffer: The current accumulated content buffer.
        is_thinking: The current state (inside or outside <think> tags).
        chunk_json: The base JSON structure of the current chunk.

    Returns:
        A tuple containing:
            - The updated buffer after processing.
            - The chunk to yield (or None if nothing to yield yet).
            - The updated thinking state.
    """
    output_chunk = None

    if is_thinking:
        # Currently thinking, look for end tag
        end_tag_match = re.search(r"</think>", buffer, re.IGNORECASE | re.DOTALL)
        if end_tag_match:
            # Found end tag
            reasoning_part = buffer[:end_tag_match.start()]
            if reasoning_part:
                output_chunk = copy.deepcopy(chunk_json)
                output_chunk["choices"][0]["delta"] = {"reasoning": reasoning_part}
                # Remove finish_reason if it exists in this intermediate chunk
                if "finish_reason" in output_chunk["choices"][0]:
                    del output_chunk["choices"][0]["finish_reason"]
            buffer = buffer[end_tag_match.end():] # Update buffer (remove tag)
            is_thinking = False # State change
        elif buffer: # No end tag found yet, but buffer has content
            # Yield entire buffer as reasoning for now
            output_chunk = copy.deepcopy(chunk_json)
            output_chunk["choices"][0]["delta"] = {"reasoning": buffer}
            if "finish_reason" in output_chunk["choices"][0]:
                del output_chunk["choices"][0]["finish_reason"]
            buffer = "" # Clear buffer as it was yielded
    else:
        # Not thinking, look for start tag
        start_tag_match = re.search(r"<think>", buffer, re.IGNORECASE | re.DOTALL)
        if start_tag_match:
            # Found start tag
            content_part = buffer[:start_tag_match.start()]
            if content_part:
                output_chunk = copy.deepcopy(chunk_json)
                output_chunk["choices"][0]["delta"] = {"content": content_part}
                if "finish_reason" in output_chunk["choices"][0]:
                    del output_chunk["choices"][0]["finish_reason"]
            buffer = buffer[start_tag_match.end():] # Update buffer (remove tag)
            is_thinking = True # State change
        elif buffer: # No start tag found, but buffer has content
            # Yield entire buffer as content
            output_chunk = copy.deepcopy(chunk_json)
            output_chunk["choices"][0]["delta"] = {"content": buffer}
            if "finish_reason" in output_chunk["choices"][0]:
                del output_chunk["choices"][0]["finish_reason"]
            buffer = "" # Clear buffer

    return buffer, output_chunk, is_thinking


async def handle_non_content_delta(buffer: str, is_thinking: bool, chunk_json: dict) -> tuple[List[dict], str]:
    """Handles delta updates without content (role changes or finish reasons).

    Yields any remaining buffer content before the final non-content chunk.

    Args:
        buffer: The current accumulated content buffer.
        is_thinking: The current state (inside or outside <think> tags).
        chunk_json: The non-content chunk received from upstream.

    Returns:
        A tuple containing:
            - A list of chunks to yield.
            - The cleared buffer.
    """
    chunks_to_yield = []

    if buffer:
        # Yield leftover buffer content first
        yield_field = "reasoning" if is_thinking else "content"
        buffer_chunk = copy.deepcopy(chunk_json) # Base structure
        buffer_chunk["choices"][0]["delta"] = {yield_field: buffer}
        # Ensure finish_reason isn't in this buffer chunk
        if "finish_reason" in buffer_chunk["choices"][0]:
            del buffer_chunk["choices"][0]["finish_reason"]
        # Clean up other potential fields if needed (optional, depends on strictness)
        if "content" in buffer_chunk["choices"][0]["delta"] and yield_field == "reasoning":
             buffer_chunk["choices"][0]["delta"]["content"] = None
        if "reasoning" in buffer_chunk["choices"][0]["delta"] and yield_field == "content":
             buffer_chunk["choices"][0]["delta"]["reasoning"] = None
        chunks_to_yield.append(buffer_chunk)
        print(f"Yielding final buffer part ({yield_field}): '{buffer}'")
        buffer = "" # Clear buffer after processing

    # Now prepare the original non-content chunk (role or finish_reason)
    final_chunk = copy.deepcopy(chunk_json)
    # Ensure it doesn't contain leftover content/reasoning fields if we just yielded buffer
    if "content" in final_chunk["choices"][0].get("delta",{}):
        final_chunk["choices"][0]["delta"]["content"] = None
    if "reasoning" in final_chunk["choices"][0].get("delta",{}):
        final_chunk["choices"][0]["delta"]["reasoning"] = None
    chunks_to_yield.append(final_chunk)
    print(f"Yielding non-content chunk: {final_chunk}")

    return chunks_to_yield, buffer


async def create_error_chunk(status_code: int, detail: Any) -> dict:
    """Creates a standardized error chunk for upstream API errors."""
    return {
        "error": {
            "message": f"Upstream API error: Status {status_code}",
            "type": "upstream_error",
            "param": None,
            "code": str(status_code),
            "detail": detail
        }
    }

async def create_proxy_error_chunk(message: str, error_type: str = "proxy_error") -> dict:
    """Creates a standardized error chunk for proxy internal errors."""
    return {
        "error": {
            "message": message,
            "type": error_type,
            "param": None,
            "code": None,
            "detail": None
        }
    }


async def stream_generator(request: ChatCompletionRequest, headers: dict) -> AsyncGenerator[str, None]:
    """Async generator to handle the streaming request to the upstream API
       and process the response chunks."""
    is_thinking = False
    buffer = ""
    client = None # Define client outside try block for potential use in finally

    try:
        # Prepare payload, ensuring stream=True
        openai_payload = request.model_dump(exclude_unset=True)
        openai_payload["stream"] = True

        client = httpx.AsyncClient()
        async with client.stream(
            "POST",
            UPSTREAM_URL,
            json=openai_payload,
            headers=headers,
            timeout=180.0 # Consider making timeout configurable
        ) as response:
            # Handle upstream errors before starting iteration
            if response.status_code >= 400:
                 error_body = await response.aread()
                 try:
                     detail = json.loads(error_body.decode())
                 except json.JSONDecodeError:
                     detail = f"Upstream API error (non-JSON): {error_body.decode()}"
                 print(f"Upstream error: {response.status_code} - {detail}")
                 error_chunk = await create_error_chunk(response.status_code, detail)
                 yield f"data: {json.dumps(error_chunk)}\n\n"
                 yield "data: [DONE]\n\n" # Signal end even on error
                 return # Stop generation

            # Process the stream line by line
            async for line in response.aiter_lines():
                if not line.strip():
                    continue

                if line.startswith("data:"):
                    data_content = line[len("data:"):].strip()

                    if data_content == "[DONE]":
                        # Process any remaining buffer before finishing
                        if buffer:
                            # This buffer content must be the last part
                            yield_field = "reasoning" if is_thinking else "content"
                            # Create a minimal chunk for the buffer content
                            buffer_chunk = {
                                "id": "proxy_final_buffer_at_done", # Indicate proxy generated
                                "object": "chat.completion.chunk",
                                "created": 0, # Placeholder
                                "model": request.model, # Use requested model
                                "choices": [{
                                    "index": 0,
                                    "delta": {yield_field: buffer},
                                    "finish_reason": None
                                }]
                            }
                            yield f"data: {json.dumps(buffer_chunk)}\n\n"
                            print(f"Yielded final buffer part at [DONE] ({yield_field}): '{buffer}'")
                            buffer = "" # Clear buffer

                        yield "data: [DONE]\n\n"
                        print("Stream finished.")
                        break # Exit the loop cleanly

                    try:
                        chunk_json = json.loads(data_content)
                        choices = chunk_json.get("choices", [])
                        if not choices: # Skip if no choices array
                            print(f"Warning: Received chunk with no choices: {data_content}")
                            continue

                        delta = choices[0].get("delta", {})
                        current_content = delta.get("content", "") or "" # Ensure string

                        # Handle non-content updates (role, finish_reason)
                        if not current_content and (delta.get("role") is not None or choices[0].get("finish_reason") is not None):
                            chunks_to_yield, buffer = await handle_non_content_delta(buffer, is_thinking, chunk_json)
                            for chunk in chunks_to_yield:
                                yield f"data: {json.dumps(chunk)}\n\n"
                            continue # Move to next line

                        # Process content if present
                        if current_content:
                            buffer += current_content
                            # Process buffer repeatedly until no more tags are found or buffer is empty
                            while True:
                                original_buffer_len = len(buffer) # To detect if processing happened
                                buffer, output_chunk, is_thinking = await process_chunk_buffer(
                                    buffer, is_thinking, chunk_json
                                )
                                if output_chunk:
                                    yield f"data: {json.dumps(output_chunk)}\n\n"
                                    print(f"Yielded processed chunk: {output_chunk['choices'][0]['delta']}")

                                # If buffer is empty or no change occurred, break inner loop
                                if not buffer or len(buffer) == original_buffer_len:
                                    break


                    except json.JSONDecodeError:
                        print(f"Warning: Could not decode JSON from upstream chunk: {data_content}")
                        continue # Skip malformed chunk
                    except Exception as e:
                        print(f"Error processing chunk: {e}")
                        import traceback
                        traceback.print_exc()
                        error_chunk = await create_proxy_error_chunk(f"Error processing chunk: {e}")
                        yield f"data: {json.dumps(error_chunk)}\n\n"
                        # Decide whether to break or continue; breaking is safer
                        break

                else:
                    print(f"Warning: Received unexpected line format from upstream: {line}")


    except httpx.RequestError as e:
        print(f"Error connecting to upstream API: {e}")
        error_chunk = await create_proxy_error_chunk(f"Upstream connection error: {e}", "upstream_error")
        yield f"data: {json.dumps(error_chunk)}\n\n"
        yield "data: [DONE]\n\n" # Ensure termination signal

    except HTTPException as e:
        # This might occur if the initial request validation fails in FastAPI before streaming
        print(f"HTTP Exception before streaming started: {e.detail}")
        # Cannot yield here as response hasn't started. Let FastAPI handle it.
        raise e # Re-raise

    except Exception as e:
        print(f"Unexpected error during streaming: {e}")
        import traceback
        traceback.print_exc() # Print full traceback for debugging
        error_chunk = await create_proxy_error_chunk(f"Internal proxy error during stream: {e}")
        yield f"data: {json.dumps(error_chunk)}\n\n"
        yield "data: [DONE]\n\n" # Ensure termination signal

    finally:
        if client:
            await client.aclose() # Ensure client is closed
        # Final check for any remaining buffer content if stream ended abruptly
        if buffer:
            final_field = "reasoning" if is_thinking else "content"
            # Create a minimal final chunk
            final_buffer_chunk = {
                "id": "proxy_final_buffer_finally", # Indicate proxy generated
                "object": "chat.completion.chunk",
                "created": 0, # Placeholder
                "model": request.model if request else "unknown", # Use requested model if available
                "choices": [{
                    "index": 0,
                    "delta": {final_field: buffer},
                    "finish_reason": None
                }]
            }
            yield f"data: {json.dumps(final_buffer_chunk)}\n\n"
            print(f"Yielded final buffer content from finally block ({final_field}): '{buffer}'")

        print("Stream generator finished.")