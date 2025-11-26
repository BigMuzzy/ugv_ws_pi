#!/bin/bash

# Script to start the mapping process using gmapping
# Usage: ./create-map.sh

echo "Starting gmapping for map creation..."
ros2 launch ugv_slam gmapping.launch.py use_rviz:=false
