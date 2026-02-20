#!/bin/bash
# Double-click this to start the trading scheduler
# Or add it to Login Items for auto-start

cd ~/trading-system
source /opt/anaconda3/etc/profile.d/conda.sh
conda activate base

# Check if already running
if curl -s http://127.0.0.1:8080/health > /dev/null 2>&1; then
    echo "Scheduler already running"
    exit 0
fi

# Start scheduler
nohup python main.py scheduler > logs/scheduler.log 2>&1 &
echo "Scheduler started with PID $!"
sleep 2

# Verify
if curl -s http://127.0.0.1:8080/health > /dev/null 2>&1; then
    echo "Health check: OK"
else
    echo "Warning: Health check failed"
fi
