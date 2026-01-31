#!/bin/bash

# Define the virtual environment python interpreter path
PYTHON_EXEC="venv/bin/python"
SCRIPT="bot.py"

echo "=========================================="
echo "Reflect-30 Watchdog Script Started"
echo "=========================================="

while true; do
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting Bot..."
    
    # Run the bot
    $PYTHON_EXEC $SCRIPT
    
    # Capture exit code
    EXIT_CODE=$?
    
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Bot stopped with exit code $EXIT_CODE"
    
    # Optional: Check for normal exit (e.g., user stopped it) if you implemented it.
    # For now, we assume any stop is unintentional or temporary and we restart.
    
    echo "Restarting in 5 seconds... (Press Ctrl+C to stop the loop)"
    sleep 5
done
