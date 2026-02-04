#!/usr/bin/env python3
"""
Mapping Mode Launch File
Launches SLAM Toolbox only - background processes (LIDAR, motors, TF) 
are already running via background.launch.py
"""

import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    # Declare arguments
    declared_arguments = [
        DeclareLaunchArgument(
            'map_path',
            default_value='/home/ws/ugv_ws/maps/new_map',
            description='Path where to save the map (without extension)'
        ),
        DeclareLaunchArgument(
            'use_rviz',
            default_value='false',
            description='Whether to launch RViz'
        ),
    ]

    # Get package directory
    ugv_slam_dir = get_package_share_directory('ugv_slam')

    # SLAM launch - with include_bringup:=false since background handles hardware
    slam_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(ugv_slam_dir, 'launch', 'slam_toolbox.launch.py')
        ),
        launch_arguments={
            'use_rviz': LaunchConfiguration('use_rviz'),
            'include_bringup': 'false',  # Background already running
        }.items()
    )

    return LaunchDescription(
        declared_arguments + [
            slam_launch,
        ]
    )