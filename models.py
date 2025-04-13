"""Pydantic models for API requests."""

from pydantic import BaseModel
from typing import Optional, List, Dict, Any

class ChatCompletionRequest(BaseModel):
    """Request model for the /v1/chat/completions endpoint."""
    model: str
    messages: List[Dict[str, Any]] # Use List/Dict/Any for broader compatibility
    stream: Optional[bool] = True
    # Add any other passthrough parameters your frontend might send
    # temperature: Optional[float] = None
    # max_tokens: Optional[int] = None
    # ... other OpenAI compatible params