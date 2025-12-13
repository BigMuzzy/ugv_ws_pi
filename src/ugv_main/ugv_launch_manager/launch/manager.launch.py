#!/usr/bin/env python3
"""
Launch Manager Launcher
Starts the launch manager node
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

    # Launch manager node
    manager_node = Node(
        package='ugv_launch_manager',
        executable='launch_manager',
        name='launch_manager',
        output='screen',
        emulate_tty=True,
        parameters=[{
            'default_mode': LaunchConfiguration('default_mode'),
            'debug': LaunchConfiguration('debug')
        }]
    )

    return LaunchDescription([
        default_mode_arg,
        debug_arg,
        manager_node,
    ])
