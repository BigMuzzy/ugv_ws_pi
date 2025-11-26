#!/bin/bash

# Script to start the navigation process
# Usage: ./navigate.sh [map_name]
# If no map name is provided, uses the default map

# Default map path
DEFAULT_MAP="/home/ws/ugv_ws/src/ugv_main/ugv_nav/maps/map.yaml"

# Check if a map name argument was provided
if [ -z "$1" ]; then
    echo "No map specified, using default map: $DEFAULT_MAP"
    MAP_PATH=$DEFAULT_MAP
else
    # If argument is provided, check if it's an absolute path or just a name
    if [[ "$1" == /* ]]; then
        # Absolute path provided
        MAP_PATH="$1"
    else
        # Just a name provided, assume it's in current directory
        MAP_PATH="$(pwd)/$1.yaml"
    fi
    echo "Using map: $MAP_PATH"
fi

# Check if map file exists
if [ ! -f "$MAP_PATH" ]; then
    echo "Error: Map file '$MAP_PATH' not found!"
    echo "Usage: ./navigate.sh [map_name or /path/to/map.yaml]"
    exit 1
fi

echo "Starting navigation with AMCL localization..."
ros2 launch ugv_nav nav.launch.py use_localization:=amcl use_rviz:=false map:=$MAP_PATH
