#!/usr/bin/env python3
"""
Navigation Mode Launch File
Launches navigation stack with AMCL localization
Reproduces: ros2 launch ugv_nav nav.launch.py use_localization:=amcl use_rviz:=false map:=/home/ws/ugv_ws/maps/second_floor.yaml
"""

import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    # Declare arguments (same as nav.launch.py expects)
    declared_arguments = [
        DeclareLaunchArgument(
            'map_path',
            default_value='/home/ws/ugv_ws/maps/second_floor.yaml',
            description='Full path to map yaml file'
        ),
        DeclareLaunchArgument(
            'use_localization',
            default_value='amcl',
            description='Localization method: amcl, emcl, cartographer'
        ),
        DeclareLaunchArgument(
            'use_localplan',
            default_value='teb',
            description='Local planner: teb, dwa'
        ),
        DeclareLaunchArgument(
            'use_rviz',
            default_value='false',
            description='Whether to launch RViz'
        ),
    ]

    # Get package directory
    ugv_nav_dir = get_package_share_directory('ugv_nav')

    # Navigation launch - directly include nav.launch.py with all arguments
    nav_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(ugv_nav_dir, 'launch', 'nav.launch.py')
        ),
        launch_arguments={
            'use_localization': LaunchConfiguration('use_localization'),
            'use_localplan': LaunchConfiguration('use_localplan'),
            'use_rviz': LaunchConfiguration('use_rviz'),
            'map': LaunchConfiguration('map_path'),
        }.items()
    )

    return LaunchDescription(
        declared_arguments + [
            nav_launch,
        ]
    )
