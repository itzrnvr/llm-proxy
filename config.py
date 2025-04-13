"""Configuration settings for the LLM proxy."""

# --- Configuration ---
UPSTREAM_URL = "https://llm.chutes.ai/v1/chat/completions" # Your upstream API (Note: This might be less relevant now with dynamic routing)

# Set of model names that are known to start their response with reasoning
# content but *omit* the opening <think> tag. They are expected to still
# include the closing </think> tag.
MODELS_OMITTING_START_THINK_TAG = {"qwen/qwq-32b", "qwen-qwq-32b"}

# --- ------------- ---