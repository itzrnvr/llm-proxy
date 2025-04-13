#!/bin/bash

PORT=8000
PROJECT_DIR="/Users/aditiaryan/Documents/code/llm-proxy"
NGROK_LOG="$PROJECT_DIR/ngrok.log"

# Python environment setup - updated to use .venv
if [ -f "$PROJECT_DIR/.venv/bin/python" ]; then
    PYTHON_PATH="$PROJECT_DIR/.venv/bin/python"
else
    PYTHON_PATH="python"
fi

cd "$PROJECT_DIR"
SERVER_COMMAND="$PYTHON_PATH -m uvicorn proxy:app --host 0.0.0.0 --port $PORT"

# Ngrok management
NGROK_PID=""
if pgrep -f "ngrok http $PORT" > /dev/null; then
    echo "Reusing existing ngrok tunnel on port $PORT"
    NGROK_RUNNING=true
else
    echo "Starting new ngrok tunnel on port $PORT..."
    ngrok http $PORT > "$NGROK_LOG" 2>&1 &
    NGROK_PID=$!
    NGROK_RUNNING=false
    sleep 3  # Give ngrok time to initialize
fi

# Get ngrok URL function
get_ngrok_url() {
    for i in {1..10}; do
        NGROK_URL=$(curl -s http://localhost:4040/api/tunnels | grep -oE 'https://[^"]*' | head -1)
        if [ -n "$NGROK_URL" ]; then
            echo "Ngrok URL: $NGROK_URL"
            return 0
        fi
        sleep 1
    done
    echo "Failed to retrieve ngrok URL"
    return 1
}

# Display URL
get_ngrok_url

# Server execution with cleanup
trap cleanup EXIT
cleanup() {
    if [ "$NGROK_RUNNING" = false ] && [ -n "$NGROK_PID" ]; then
        echo "Cleaning up ngrok process"
        kill $NGROK_PID 2>/dev/null
    fi
}

echo "Starting server on port $PORT..."
PYTHONPATH="$PROJECT_DIR" $SERVER_COMMAND
SERVER_EXIT_CODE=$?

exit $SERVER_EXIT_CODE