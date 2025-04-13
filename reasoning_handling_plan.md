# Plan: Handling Models Omitting Start `<think>` Tag

**Goal:** Modify the proxy to correctly identify initial reasoning content even when the `<think>` tag is missing, provided the model name indicates this behavior and the `</think>` tag is present later.

**Approach:** Introduce a configuration setting within the proxy to list models known to exhibit this behavior. The streaming logic will check the requested model against this list to determine the initial state for parsing.

**Detailed Plan:**

1.  **Configuration Update (`config.py`):**
    *   Define a set or list containing the names of models that start with reasoning but omit the opening `<think>` tag.
    *   Example:
        ```python
        # config.py
        # Add this set to your config file
        MODELS_OMITTING_START_THINK_TAG = {"qwq-32b"}
        ```

2.  **Modify Streaming Logic (`streaming.py`):**
    *   **Import Configuration:** Import `MODELS_OMITTING_START_THINK_TAG` from `config.py` at the top of `streaming.py`.
    *   **Conditional Initialization:** Inside the `stream_generator` function, right before the main processing loop begins (around line 151), determine the initial value for the `is_thinking` state variable based on the requested model name.
        ```python
        # streaming.py (inside stream_generator)

        from config import MODELS_OMITTING_START_THINK_TAG # Import the set
        # ... other imports ...

        async def stream_generator(target_url: str, request: ChatCompletionRequest, headers: dict) -> AsyncGenerator[str, None]:
            """Async generator to handle the streaming request..."""

            # --- MODIFICATION START ---
            # Determine initial state based on model name
            initial_thinking_state = request.model in MODELS_OMITTING_START_THINK_TAG
            is_thinking = initial_thinking_state
            buffer = ""
            client = None
            print(f"Initializing stream for model '{request.model}'. Starts with reasoning: {initial_thinking_state}. Initial state set to is_thinking={is_thinking}")
            # --- MODIFICATION END ---

            try:
                # ... rest of the function remains the same ...
        ```
    *   **No Changes to `process_chunk_buffer`:** The existing `process_chunk_buffer` function should handle this correctly. If `is_thinking` starts as `True`, it will correctly look for the `</think>` tag to transition out of the thinking state and will treat preceding content as reasoning.

3.  **Testing:**
    *   Test with a standard model (e.g., `gpt-4`) to ensure it still correctly parses `<think>...</think>` blocks.
    *   Test with the specified model (`qwq-32b`) sending a response that starts with reasoning text and includes `</think>` later, confirming the initial text is captured as `reasoning`.

**Rationale:**

*   **Centralized Configuration:** Keeping the list of special models in `config.py` makes it easy to manage and update without changing the core streaming logic frequently.
*   **Minimal Code Change:** This approach requires only a small modification to initialize the state correctly, leveraging the existing parsing logic in `process_chunk_buffer`.
*   **Robustness:** It directly addresses the specified variation without relying on potentially fragile inference based on initial chunk content.

**Visual Plan (Mermaid Diagram):**

```mermaid
graph TD
    subgraph Initialization
        A[Request Received] --> B{Get Model Name};
        B --> C{Check if Model in MODELS_OMITTING_START_THINK_TAG};
        C -- Yes --> D[Set is_thinking = True];
        C -- No --> E[Set is_thinking = False];
    end

    subgraph Streaming Loop
        F[Start stream_generator with initial is_thinking state] --> G{Receive Chunk};
        G --> H[Append chunk content to buffer];
        H --> I{Process Buffer (process_chunk_buffer)};
        I -- based on is_thinking state --> J{Look for <think> or </think>};
        J -- Tag Found --> K[Yield Content/Reasoning, Update is_thinking, Update Buffer];
        J -- Tag Not Found / Buffer Processed --> L[Yield Content/Reasoning (Intermediate)];
        K --> G;
        L --> G;
        G -- [DONE] Received --> M[Yield Final Buffer Content];
        M --> N[End Stream];
    end

    D --> F;
    E --> F;

    style D fill:#f9d,stroke:#333,stroke-width:2px
    style E fill:#ccf,stroke:#333,stroke-width:2px