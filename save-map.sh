#!/bin/bash

# Script to save the current map
# Usage: ./save-map.sh [map_name]
# If no map name is provided, uses 'map' as default

# Default map name
DEFAULT_MAP_NAME="map"

# Check if a map name argument was provided
if [ -z "$1" ]; then
    MAP_NAME=$DEFAULT_MAP_NAME
    echo "No map name specified, using default: $MAP_NAME"
else
    MAP_NAME="$1"
    echo "Saving map as: $MAP_NAME"
fi

# Save the map
echo "Running map_saver_cli..."
ros2 run nav2_map_server map_saver_cli -f "$MAP_NAME"

# Check if the save was successful
if [ $? -eq 0 ]; then
    echo "Map saved successfully!"
    echo "Created files:"
    echo "  - ${MAP_NAME}.pgm"
    echo "  - ${MAP_NAME}.yaml"
    ls -lh "${MAP_NAME}.pgm" "${MAP_NAME}.yaml" 2>/dev/null
else
    echo "Error: Failed to save map. Make sure gmapping is running and publishing to /map topic."
    exit 1
fi
