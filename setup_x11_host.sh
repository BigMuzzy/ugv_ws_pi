#!/bin/bash
# Script to set up X11 forwarding for Docker on Raspberry Pi HOST
# Run this on the Raspberry Pi (outside container) after SSH connection
# Usage: ./setup_x11_host.sh

CONTAINER_NAME="ugv_rpi_ros_humble_new"

# Check if DISPLAY is set
if [ -z "$DISPLAY" ]; then
    echo "Error: DISPLAY environment variable is not set!"
    echo "Make sure you connected with: ssh -X user@host"
    exit 1
fi

echo "Current DISPLAY: $DISPLAY"

# Extract display number
DISPLAY_NUM=$(echo $DISPLAY | sed 's/.*:\([0-9]*\).*/\1/')
echo "Display number: $DISPLAY_NUM"

# Get the auth cookie for this display
COOKIE=$(xauth list | grep "raspberrypi/unix:$DISPLAY_NUM" | awk '{print $3}')

if [ -z "$COOKIE" ]; then
    echo "Warning: Could not find auth cookie for display :$DISPLAY_NUM"
    echo "Available auth entries:"
    xauth list
    exit 1
fi

echo "Found auth cookie: ${COOKIE:0:20}..."

# Check if container exists
if [ "$(docker ps -aq -f name=$CONTAINER_NAME)" ]; then
    echo "Configuring X11 authentication in container..."
    
    # Remove old entries for this display to avoid conflicts
    docker exec $CONTAINER_NAME xauth remove raspberrypi/unix:$DISPLAY_NUM 2>/dev/null
    docker exec $CONTAINER_NAME xauth remove localhost:$DISPLAY_NUM 2>/dev/null
    docker exec $CONTAINER_NAME xauth remove 127.0.0.1:$DISPLAY_NUM 2>/dev/null
    docker exec $CONTAINER_NAME xauth remove ugvrpi/unix:$DISPLAY_NUM 2>/dev/null
    
    # Add fresh auth entries
    docker exec $CONTAINER_NAME xauth add raspberrypi/unix:$DISPLAY_NUM MIT-MAGIC-COOKIE-1 $COOKIE
    docker exec $CONTAINER_NAME xauth add localhost:$DISPLAY_NUM MIT-MAGIC-COOKIE-1 $COOKIE
    docker exec $CONTAINER_NAME xauth add 127.0.0.1:$DISPLAY_NUM MIT-MAGIC-COOKIE-1 $COOKIE
    docker exec $CONTAINER_NAME xauth add ugvrpi/unix:$DISPLAY_NUM MIT-MAGIC-COOKIE-1 $COOKIE
    
    echo "✓ X11 authentication configured for display :$DISPLAY_NUM"
    echo "  Added entries for: raspberrypi, localhost, 127.0.0.1, ugvrpi"
else
    echo "Warning: Container '$CONTAINER_NAME' not found."
    echo "Start the container first, then run this script again."
    exit 1
fi

echo ""
echo "✓ Setup complete! Now you can run: ./enter_container.sh"
