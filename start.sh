#!/bin/bash
# Fallback port if not set in environment
PORT=${PORT:-8000}

# Start the application with the correct port
uvicorn main:app --host 0.0.0.0 --port $PORT
