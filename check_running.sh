#!/bin/bash
# Check if Ergane is already running and optionally kill it

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Find processes running main.py from THIS directory
PIDS=$(ps aux | grep "python3.*${SCRIPT_DIR}/main.py" | grep -v grep | awk '{print $2}')

if [ -n "$PIDS" ]; then
    RUNNING=$(echo "$PIDS" | wc -l)
    echo "⚠️  Found $RUNNING running instance(s) of Ergane:"
    ps aux | grep "python3.*${SCRIPT_DIR}/main.py" | grep -v grep
    
    if [ "$1" == "--kill" ]; then
        echo ""
        echo "🔪 Killing all instances..."
        for pid in $PIDS; do
            kill -9 $pid 2>/dev/null && echo "  Killed PID $pid"
        done
        sleep 1
        echo "✅ Instances killed. You can now restart Ergane."
    else
        echo ""
        echo "💡 To kill them, run: $0 --kill"
        echo "   Or manually: kill -9 <PID>"
        exit 1
    fi
else
    echo "✅ No running Ergane instances found. Safe to start!"
fi
