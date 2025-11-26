#!/bin/bash
# Script to enter the ROS2 Docker container with X11 forwarding enabled
# Usage: ./enter_container.sh

CONTAINER_NAME="ugv_rpi_ros_humble"

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

# Enter the container with X11 forwarding
docker exec -it -e DISPLAY=localhost:12.0 $CONTAINER_NAME bash
