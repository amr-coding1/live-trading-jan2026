#!/bin/bash
# Wrapper script for LaunchAgent to properly initialize conda environment
# This script is called by launchd at login

# Redirect stdin from /dev/null (launchd doesn't provide stdin)
exec 0</dev/null

# Set HOME explicitly (launchd might not set it)
export HOME="/Users/abdulrahmanm"

# Initialize conda
if [ -f "/opt/anaconda3/etc/profile.d/conda.sh" ]; then
    source /opt/anaconda3/etc/profile.d/conda.sh
    conda activate base
else
    echo "Error: conda.sh not found" >&2
    exit 1
fi

# Change to project directory
cd "$HOME/trading-system" || exit 1

# Run scheduler
exec python main.py scheduler
