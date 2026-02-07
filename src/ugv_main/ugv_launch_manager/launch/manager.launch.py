#!/usr/bin/env python3
"""
Mode Manager Launcher
Starts the mode manager node (lifecycle-based mode switching)
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    # Declare launch argument for default mode
    default_mode_arg = DeclareLaunchArgument(
        'default_mode',
        default_value='idle',
        description='Mode to start automatically on launch (idle, mapping, navigation, or none)'
    )

    # Declare launch argument for debug mode
    debug_arg = DeclareLaunchArgument(
        'debug',
        default_value='false',
        description='Enable debug mode - show all subprocess output to console (true/false)'
    )

    # Mode manager node (lifecycle-based)
    manager_node = Node(
        package='ugv_launch_manager',
        executable='mode_manager',
        name='mode_manager',
        output='screen',
        emulate_tty=True,
        parameters=[{
            'default_mode': LaunchConfiguration('default_mode'),
            'debug': LaunchConfiguration('debug'),
            'transition_timeout': 10.0,
            'map_save_path': '/home/ws/ugv_ws/maps/current_map',
            'maps_directory': '/home/ws/ugv_ws/maps',
        }]
    )

    return LaunchDescription([
        default_mode_arg,
        debug_arg,
        manager_node,
    ])
