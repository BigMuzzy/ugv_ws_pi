#!/usr/bin/env python3
"""Mapping Mode Launch File

Primary backend:
- UGV mapping via ugv_slam gmapping

Fallback backend (when ugv_slam is not installed, e.g., TurtleBot3 sim container):
- nav2_bringup navigation_launch.py + slam_toolbox online_async_launch.py
"""

import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import SetParameter
from ament_index_python.packages import PackageNotFoundError, get_package_share_directory


def generate_launch_description():
    # Declare arguments (same as gmapping.launch.py expects)
    declared_arguments = [
        DeclareLaunchArgument(
            'use_sim_time',
            default_value='false',
            description='Use simulation clock (/clock)'
        ),
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

    actions = [
        SetParameter(name='use_sim_time', value=LaunchConfiguration('use_sim_time')),
    ]

    # Prefer UGV gmapping if available.
    try:
        ugv_slam_dir = get_package_share_directory('ugv_slam')

        actions.append(
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(ugv_slam_dir, 'launch', 'gmapping.launch.py')
                ),
                launch_arguments={
                    'use_rviz': LaunchConfiguration('use_rviz'),
                }.items(),
            )
        )

    except PackageNotFoundError:
        # TurtleBot3-friendly fallback: Nav2 bringup + slam_toolbox.
        nav2_bringup_dir = get_package_share_directory('nav2_bringup')
        slam_toolbox_dir = get_package_share_directory('slam_toolbox')

        actions.extend(
            [
                IncludeLaunchDescription(
                    PythonLaunchDescriptionSource(
                        os.path.join(nav2_bringup_dir, 'launch', 'navigation_launch.py')
                    ),
                    launch_arguments={
                        'use_sim_time': LaunchConfiguration('use_sim_time'),
                    }.items(),
                ),
                IncludeLaunchDescription(
                    PythonLaunchDescriptionSource(
                        os.path.join(slam_toolbox_dir, 'launch', 'online_async_launch.py')
                    ),
                    launch_arguments={
                        'use_sim_time': LaunchConfiguration('use_sim_time'),
                    }.items(),
                ),
            ]
        )

    return LaunchDescription(declared_arguments + actions)
