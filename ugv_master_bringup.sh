#!/bin/bash

# UGV Master Bringup Script
# This script launches the camera and navigation systems

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}UGV Master Bringup Script${NC}"
echo -e "${GREEN}========================================${NC}"

# Store PIDs for cleanup
PIDS=()

# Cleanup function
cleanup() {
    echo -e "\n${YELLOW}Shutting down...${NC}"

    # Kill all child processes
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            echo -e "${YELLOW}Stopping process $pid${NC}"
            kill -SIGINT "$pid" 2>/dev/null
        fi
    done

    # Wait a bit for graceful shutdown
    sleep 2

    # Force kill if still running
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            echo -e "${RED}Force killing process $pid${NC}"
            kill -9 "$pid" 2>/dev/null
        fi
    done

    echo -e "${GREEN}Shutdown complete${NC}"
    exit 0
}

# Set up trap to catch Ctrl+C and other termination signals
trap cleanup SIGINT SIGTERM

echo -e "${GREEN}[1/2] Launching OAK-D Lite Camera...${NC}"
ros2 launch ugv_vision oak_d_lite.launch.py &
PIDS+=($!)
sleep 10  # Give camera time to initialize

echo -e "${GREEN}[2/2] Launching Navigation Stack...${NC}"
ros2 launch ugv_nav nav.launch.py \
    use_localization:=amcl \
    use_rviz:=false \
    map:=/home/ws/ugv_ws/maps/second_floor.yaml &
PIDS+=($!)
sleep 10

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}All systems launched!${NC}"
echo -e "${YELLOW}Press Ctrl+C to stop all processes${NC}"
echo -e "${GREEN}========================================${NC}"

# Wait for all background processes
wait
