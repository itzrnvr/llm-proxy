"""Configuration settings for the LLM proxy."""

# --- Configuration ---
UPSTREAM_URL = "https://llm.chutes.ai/v1/chat/completions" # Your upstream API (Note: This might be less relevant now with dynamic routing)

# Set of model names that are known to start their response with reasoning
# content but *omit* the opening <think> tag. They are expected to still
# include the closing </think> tag.
MODELS_OMITTING_START_THINK_TAG = {"qwen/qwq-32b", "qwen-qwq-32b"}

# Dictionary mapping provider IDs to their FULL target URLs for the /provider endpoint
PREBUILT_PROVIDERS = {
    "chutes": "https://llm.chutes.ai/v1/chat/completions", # Example using the standard path
    "azurdr1": "https://ai-e22cseu07147843ai803076773836.services.ai.azure.com/models/chat/completions",
    "azureo3": "https://openaiv.openai.azure.com/openai/deployments/o3-mini/chat/completions?api-version=2025-01-01-preview"
    # Add other pre-configured providers with their full URLs here, e.g.:
    # "another_provider": "https://api.anotherprovider.com/custom/path/endpoint"
}

# --- ------------- ---