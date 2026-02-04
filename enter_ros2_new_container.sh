#!/bin/bash
# Script to enter the ROS2 Docker container with X11 forwarding enabled
# Uses tmux for session management - multiple windows, persistent sessions
# Usage: ./enter_container.sh [new]
#   no args  - attach to existing tmux session or create one
#   new      - create a new tmux window in existing session

CONTAINER_NAME="ugv_rpi_ros_humble_new"
TMUX_SESSION="ros"

# Check if container is running
if [ "$(docker ps -q -f name=$CONTAINER_NAME)" ]; then
    echo "Container is already running. Entering container..."
else
    # Check if container exists but is stopped
    if [ "$(docker ps -aq -f name=$CONTAINER_NAME)" ]; then
        echo "Container exists but is stopped. Starting container..."
        docker start $CONTAINER_NAME
    else
        echo "Error: Container '$CONTAINER_NAME' does not exist!"
        exit 1
    fi
fi

# Environment variables for the container
DOCKER_ENV="-e DISPLAY=localhost:10.0 -e UGV_MODEL=ugv_rover -e LDLIDAR_MODEL=ld19"

# Check if tmux session exists inside container
if docker exec $CONTAINER_NAME tmux has-session -t $TMUX_SESSION 2>/dev/null; then
    if [ "$1" = "new" ]; then
        # Create new window in existing session
        echo "Creating new tmux window in session '$TMUX_SESSION'..."
        docker exec -it $DOCKER_ENV $CONTAINER_NAME tmux new-window -t $TMUX_SESSION
        docker exec -it $DOCKER_ENV $CONTAINER_NAME tmux attach -t $TMUX_SESSION
    else
        # Attach to existing session
        echo "Attaching to existing tmux session '$TMUX_SESSION'..."
        echo "Tip: Use './enter_ros2_new_container.sh new' to open a new window"
        docker exec -it $DOCKER_ENV $CONTAINER_NAME tmux attach -t $TMUX_SESSION
    fi
else
    # Create new tmux session
    echo "Creating new tmux session '$TMUX_SESSION'..."
    docker exec -it $DOCKER_ENV $CONTAINER_NAME tmux new -s $TMUX_SESSION
fi
