# LLM Proxy Refactoring Plan: Generalized Provider Handling

This plan outlines the refactoring of the LLM proxy to support multiple upstream API providers in a generalized way, based on user feedback.

**Core Idea:** The proxy will act as a generic forwarder, dynamically routing requests based on the URL provided by the client. It will apply universal `<think>` tag processing to all responses and pass through authentication headers.

**Revised Plan:**

1.  **Dynamic Endpoint Routing (`proxy.py`):**
    *   Modify the FastAPI endpoint to capture the target provider's base URL from the path. The new path structure will be: `/proxy/{provider_base_url:path}/v1/chat/completions`.
    *   The `{provider_base_url:path}` parameter will capture the full base URL of the target provider (e.g., `https://llm.chutes.ai`).
    *   The endpoint function will construct the full `target_url` by combining the captured `provider_base_url` and the fixed `/v1/chat/completions` suffix.

2.  **Generalized Streaming Logic (`streaming.py`):**
    *   Update the `stream_generator` function to accept the dynamically constructed `target_url` as a parameter.
    *   The existing logic for processing `<think>` tags will be applied universally to the stream received from any `target_url`.

3.  **Passthrough Authentication (`proxy.py`):**
    *   Maintain the current logic to extract the `Authorization` header from the incoming client request and pass it directly to the upstream API via the `stream_generator`.

4.  **Configuration (`config.py`):**
    *   The hardcoded `UPSTREAM_URL` constant becomes obsolete for routing and can be removed or commented out.

**Revised Flow (Mermaid Diagram):**

```mermaid
graph TD
    ClientRequest -->|POST /proxy/{provider_base_url}/v1/chat/completions| ProxyEndpoint[proxy.py: Endpoint];
    ProxyEndpoint -->|Extracts provider_base_url| UrlBuilder{URL Construction};
    UrlBuilder -->|Constructs target_url| StreamingFunc[streaming.py: stream_generator];
    ProxyEndpoint -->|Passes Headers (incl. Auth)| StreamingFunc;
    ProxyEndpoint -->|Passes Request Body| StreamingFunc;

    StreamingFunc -->|POST target_url| DynamicUpstreamAPI[Target Provider API];
    DynamicUpstreamAPI -->|Streams Response| StreamingFunc;
    StreamingFunc -->|Processes <think> tags (Always)| StreamingFunc;
    StreamingFunc -->|Streams SSE| ProxyEndpoint;
    ProxyEndpoint -->|Streams SSE| ClientResponse[Client];

    subgraph Proxy Application
        ProxyEndpoint
        UrlBuilder
        StreamingFunc
    end

    subgraph Upstream APIs
        DynamicUpstreamAPI
    end
```

**Example (Chutes API):**

*   Client sends POST to: `http://<proxy_address>/proxy/https://llm.chutes.ai/v1/chat/completions`
*   Proxy extracts `https://llm.chutes.ai` as `provider_base_url`.
*   Proxy constructs `target_url`: `https://llm.chutes.ai/v1/chat/completions`.
*   Proxy calls `stream_generator` with this `target_url` and client's headers/body.
*   `stream_generator` forwards the request to the Chutes API.
*   `stream_generator` processes the response (including `<think>` tags) and streams back to the client.