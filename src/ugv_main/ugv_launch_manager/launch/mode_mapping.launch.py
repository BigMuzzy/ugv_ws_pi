#!/usr/bin/env python3
"""
Mapping Mode Launch File
Launches SLAM system with gmapping
Reproduces: ros2 launch ugv_slam gmapping.launch.py use_rviz:=false
"""

import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    # Declare arguments (same as gmapping.launch.py expects)
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

    # SLAM launch - directly include gmapping.launch.py
    slam_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(ugv_slam_dir, 'launch', 'gmapping.launch.py')
        ),
        launch_arguments={
            'use_rviz': LaunchConfiguration('use_rviz'),
        }.items()
    )

    return LaunchDescription(
        declared_arguments + [
            slam_launch,
        ]
    )
